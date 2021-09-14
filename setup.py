#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open('README.md') as readme_file:
    readme = readme_file.read()

with open('HISTORY.md') as history_file:
    history = history_file.read()

requirements = [
    'fab-classic',
]

test_requirements = ['pytest>=3', ]

setup(
    author="Ivan Savov",
    author_email='ivan@minireference.com',
    python_requires='>=3.6',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    description="Reusable automation tasks and scripts based on fab-classic: cloud provisiotning, docker, etc.",
    entry_points={},
    install_requires=requirements,
    license="MIT license",
    long_description=readme + '\n\n' + history,
    long_description_content_type='text/markdown',
    include_package_data=True,
    keywords='fabfiles',
    name='fabfiles',
    packages=find_packages(include=['fabfiles', 'fabfiles.*']),
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/minireference/fabfiles',
    version='0.1.0',
    zip_safe=False,
)
