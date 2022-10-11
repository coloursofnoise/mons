# CONTRIBUTING

## Asking for help
If you are looking for help with setting up or using `mons`, or you have other questions about how the program works and how you can contribute, please use the `#modding_help` or `#modding_dev` channels in the Celeste Community Discord: https://discord.gg/celeste

## Before contributing
- Check the [existing issues](https://github.com/coloursofnoise/mons/issues) to see if your request has already been made.
  - If so, add a comment to describe how you plan to resolve it and request to have the issue assigned to you.
- If an issue does not already exist, create one describing your request and how you plan on implementing it.

## First time setup
- Clone the GitHub repository locally
```console
$ git clone https://github.com/coloursofnoise/mons.git
$ cd mons
```
- Create a virtualenv
```console
$ python3 -m venv env
$ . env/bin/activate
```
- Upgrade `pip` and `setuptools`
```console
$ python -m pip install --upgrade pip setuptools
```
- Install development dependencies, then install `mons` in editable mode
```console
$ pip install -r requirements-dev.txt
$ pip install -e .
```
- Install the [pre-commit](https://pre-commit.com) hooks
```console
$ pre-commit install
```

## Writing code
When making changes to the project, follow best practices for code and version control wherever possible:
- Commit frequently, with clear commit messages.
- Use [Black](https://black.readthedocs.io) to format your code. This and other tools will run automatically if you install [pre-commit](https://pre-commit.com) using the instructions above.
- Add tests to verify your code. Added tests should fail without your changes.
- Add or update docstrings and other relevant documentation.
- When creating your pull request, provide a short explanation for your changes and link to the issue being addressed: https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue

## Running tests
### `pytest`
Run tests for the current environment with `pytest`
```console
$ pytest
```
To run end-to-end tests using a local Celeste install, run `pytest` and provide the path for the Celeste install

:warning: When tests fail they can break the install they are run on. **Do not use a Celeste install you care about.**
```console
$ pytest --mons-test-install={/path/to/Celeste/install}
```
### `tox`
The full suite of tests can be run with `tox`. This will also be run by the CI server when a pull request is submitted
```console
$ tox
```
End-to-end tests can also be run with `tox`
```console
$ tox -- --mons-test-install={/path/to/Celeste/install}
```

# MAINTAINERS
## Releasing a new version
- Tag a commit with the format `v{version number}` where {version number} follows the [semver](https://semver.org/) specification.
- The CI server will run tests, then build and upload the new version to [PyPI](https://pypi.org/project/mons/).
- (Optional) Create a [GitHub release](https://github.com/coloursofnoise/mons/releases) for the new tag once CI has completed successfully.
