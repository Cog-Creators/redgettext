from setuptools import setup

with open("README.rst") as file:
    readme = file.read()

setup(
    name="redgettext",
    author="Tobotimus",
    description="A slightly modified pygettext for Red-DiscordBot",
    long_description=readme,
    url="https://github.com/Tobotimus/redgettext",
    version="1.0",
    license="GPL-3.0",
    install_requires=[],
    py_modules=["redgettext"],
    namespace_packages=[],
    include_package_data=True,
    entry_points={"console_scripts": ["redgettext=redgettext:main"]}
)
