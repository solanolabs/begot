# begot

[![](https://ci.solanolabs.com:443/solanolabs/begot/badges/155480.png)](https://ci.solanolabs.com:443/solanolabs/begot/suites/155480)

Begot is a Go dependency manager and build tool. Please read the docstring at
the top of begot.py for a discussion of motivation, design decisions, and
documentation.

Begot is currently written in Python (2.x), though it may be rewritten in Go at
some point in the future. It requires the PyYAML library (`python-yaml` in
Ubuntu or Fedora or `pip install pyyaml`).

Begot is released under a simplified BSD license.

## quick start

Prerequisites:

- Clone this repo and `ln -s path/to/begot.py ~/bin/begot`.

Converting an existing project:

- Delete any previously-vendored dependencies.
- Create a `Begotten` file with simple names for your dependencies.
- Rewrite import paths in your project to refer to the new dependency names.
- Rewrite import paths in your project to refer to other packages in your
  project repo with paths relative to the repo root.
- Run `begot update`.
- Run `begot build`.
- Commit `Begotten` and `Begotten.lock`.

Building a project using begot:

- Clone/update the project repo.
- Run `begot fetch`.
- Run `begot build`.

See the documentation in `begot.py` or run `begot help` for more details.
