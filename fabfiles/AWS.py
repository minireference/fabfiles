import os

import boto3
from fabric.api import env, task, local, sudo, run, settings
from fabric.api import get, put, require
from fabric.colors import red, green, blue, yellow
from fabric.context_managers import cd, prefix, show, hide, shell_env
from fabric.contrib.files import exists, sed, upload_template
from fabric.utils import puts



# credentials
ACCESS_KEY = os.environ.get('ACCESS_KEY')
SECRET_ACCESS_KEY = os.environ.get('SECRET_ACCESS_KEY')

# AWS settings
AWS_REGION = "ca-central-1"
AWS_AVAILABILITY_ZONE = "ca-central-1a"
AWS_INSTACE_TYPE = "t2.micro"
AWS_INSTANCE_VOLUME_SIZE = 20

# OS settings
DEBAIN_AMI_IMAGE_ID = "ami-030d779d5a11f6000"  # debian-10-amd64-20211011-792
# via https://wiki.debian.org/Cloud/AmazonEC2Image/Buster



# client (old style API)
ec2c = boto3.client(
    'ec2',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)

# resources (new style API)
ec2r = boto3.resource(
    'ec2',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)




# TASKS
################################################################################


@task
def provision_landscape(name="TEST"):
    """
    Provision a complete AWS landscape:
    - VPC
    - Subnet
    - Internet Gateway & Route Table
    - Security Group with open ports: 21, 80, 8000, 8080
    - Allocate an Elastic IP
    - Create an EC2 Instance and associate the Elastic IP to it
    """
    vpc_cidr_block = '10.100.0.0/16'
    subnet_cidr_block = '10.100.10.0/24'

    # create VPC
    vpc = ec2r.create_vpc(CidrBlock=vpc_cidr_block)
    vpc.create_tags(Resources=[vpc.id], Tags=[{"Key": "Name", "Value": name+"-vpc"}])
    print('Created VPC', vpc.id)

    # create an internet gateway and attach it to VPC
    ig = ec2r.create_internet_gateway()
    print('Created internet gateway', ig.id)
    vpc.attach_internet_gateway(InternetGatewayId=ig.id)

    # create a route table and a route to public internet
    routetable = vpc.create_route_table()
    routetable.create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)
    print('Created route table', routetable.id)

    # create subnet and associate it with route table
    subnet = ec2r.create_subnet(CidrBlock=subnet_cidr_block, VpcId=vpc.id, AvailabilityZone=AWS_AVAILABILITY_ZONE)
    routetable.associate_with_subnet(SubnetId=subnet.id)
    print('Created subnet', subnet.id)

    # create a security group suitable for a web server
    sg = ec2r.create_security_group(GroupName=name+'-webserver-sg', Description='ssh and web ports 21 80 443 8000 8080', VpcId=vpc.id)
    sg.authorize_ingress(CidrIp='0.0.0.0/0', IpProtocol='tcp', FromPort=22, ToPort=22)
    sg.authorize_ingress(CidrIp='0.0.0.0/0', IpProtocol='tcp', FromPort=80, ToPort=80)
    sg.authorize_ingress(CidrIp='0.0.0.0/0', IpProtocol='tcp', FromPort=443, ToPort=443)
    sg.authorize_ingress(CidrIp='0.0.0.0/0', IpProtocol='tcp', FromPort=8000, ToPort=8000)
    sg.authorize_ingress(CidrIp='0.0.0.0/0', IpProtocol='tcp', FromPort=8080, ToPort=8080)
    print('Created security group', sg.id, sg.group_name)

    # allocate Elastic IP for the instance
    public_ip = provision_address(name=name+'-elastic-ip')
    allocation_id = get_allocation_id_for_address(public_ip)

    # create instance
    ec2r.create_instances(
        ImageId=DEBAIN_AMI_IMAGE_ID,
        InstanceType=AWS_INSTACE_TYPE, MaxCount=1, MinCount=1,
        KeyName='fabfiles-admin',  # the ssh keypair in credentials/admin{.pub}
        NetworkInterfaces=[{
            'SubnetId': subnet.id,
            'DeviceIndex': 0,
            'AssociatePublicIpAddress': False,
            'Groups': [sg.group_id]
        }],
        BlockDeviceMappings=[{
            "DeviceName": "/dev/xvda",
            "Ebs": {
                "VolumeSize": AWS_INSTANCE_VOLUME_SIZE,
                "DeleteOnTermination": True
            }
        }],
    )
    instance = list(vpc.instances.all())[0]
    vpc.create_tags(Resources=[instance.id], Tags=[{"Key": "Name", "Value": name+"-instance"}])
    print('Create instance issued', instance.id, 'waiting to be running ...')
    instance.wait_until_running()
    print('   ... instance', instance.id, 'is now running')

    # associate Elastic IP with instance
    ec2c.associate_address(AllocationId=allocation_id, InstanceId=instance.id)
    print('Associated', public_ip, 'with instance', instance.id)

    print('DONE provisioning AWS landscape', name, 'VPC id = ', vpc.id)
    puts(blue('Login to instance using:     ssh -i credentials/admin admin@' + public_ip))




@task
def destroy_landscape(vpc_id=None, name="TEST"):
    """
    Destrop a complete AWS landscape:
    - Release Elastic IP
    - Terminate EC2 Instance
    - Delete Security Group, Subnet, Route Table, Internet Gateway
    - Delete VPC
    """
    vpc = ec2r.Vpc(vpc_id)

    # A. destroy_all_vpc_instances
    ############################################################################
    for instance in vpc.instances.all():
        # disassocite and release any associated elastic ips
        addresses = instance.vpc_addresses.all()
        for adr in addresses:
            assert adr.instance_id == instance.id
            adr.association.delete()
            print('releasing elastic ip', adr.public_ip)
            adr.release()
        print('terminating instance', instance.id)
        instance.terminate()
        instance.wait_until_terminated()


    # B. destroy_network
    ############################################################################
    # 1. delete security groups
    for sg in vpc.security_groups.all():
        if sg.group_name == "default":
            continue  # skip default security group
        print('deleting security group', sg.id, sg.group_name)
        sg.delete()

    # 2. delete subnets
    for subnet in vpc.subnets.all():
        print('deleting subnet', subnet.id)
        subnet.delete()

    # 3. delete route tables
    for route_table in vpc.route_tables.all():
        if is_main_route_table(route_table):
            continue  # skip main route table
        print('deleting route table', route_table.id)
        route_table.delete()

    # 4. delete internet gateway
    for ig in vpc.internet_gateways.all():
        print('deleting internet gateway', ig.id)
        ig.detach_from_vpc(VpcId=vpc.id)
        ig.delete()

    # 5. delete VPC
    vpc.delete()

    print("VPC", vpc_id, "sucessfully destroyed")







# UTILS
################################################################################

def provision_address(name="my-elastic-ip"):
    """
    Provision an Elastic IP address and return public_ip as a string.
    """
    allocation = ec2c.allocate_address(Domain='vpc')
    ec2c.create_tags(
        Resources=[allocation['AllocationId']],
        Tags=[{"Key": "Name", "Value": name}],
    )
    print('Allocated Elastic IP', allocation['PublicIp'], name, allocation['AllocationId'])
    return allocation['PublicIp']



def get_allocation_id_for_address(public_ip):
    """
    Lookup the allocation ID for the given Elastic IP address.
    """
    response = ec2c.describe_addresses(PublicIps=[public_ip])
    return response['Addresses'][0]['AllocationId']



def is_main_route_table(route_table):
    is_main = False
    for association in route_table.associations:
        if association.main:
            is_main = True
    return is_main

