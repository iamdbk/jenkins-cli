from setuptools import setup, find_packages

setup(
    name="jenkins-cli",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "python-jenkins>=1.7.0",
        "click>=8.0.0",
        "python-dotenv>=1.0.0",
        "tabulate>=0.9.0",
        "requests>=2.25.0",
    ],
    entry_points={
        "console_scripts": [
            "j=jenkins_cli.test_collateral:main",
        ],
    },
)
