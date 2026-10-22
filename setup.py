"""
EmberBurn Industrial IoT Gateway Setup
This file enables GitHub dependency detection and security scanning.
"""

from setuptools import setup, find_packages

from version import __version__

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="emberburn",
    version=__version__,
    author="Patrick Ryan",
    author_email="patrick@fireballz.ai",
    description="Multi-Protocol Industrial IoT Gateway with OPC UA Server",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/fireball-industries/Small-Application",
    project_urls={
        "Bug Tracker": "https://github.com/fireball-industries/Small-Application/issues",
        "Documentation": "https://fireballz.ai/emberburn",
        "Source Code": "https://github.com/fireball-industries/Small-Application",
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Manufacturing",
        "Topic :: System :: Monitoring",
        "Topic :: Software Development :: Testing",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    packages=find_packages(exclude=["tests*", "docs*", "helm*", "scripts*"]),
    python_requires=">=3.11",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "emberburn=opcua_server:main",
        ],
    },
    include_package_data=True,
    keywords="opcua, industrial-iot, scada, mqtt, modbus, prometheus, graphql, data-transformation",
)
