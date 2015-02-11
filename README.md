# begot

[![](https://ci.solanolabs.com:443/solanolabs/begot/badges/155480.png)](https://ci.solanolabs.com:443/solanolabs/begot/suites/155480)

Begot is a Go dependency manager and build tool. Please read doc.txt for a
discussion of motivation, design decisions, and usage instructions.

Begot is released under a simplified BSD license.

## quick start

Prerequisites:

- Clone this repo and `cd begot && make && install ./begot ~/bin/begot`.

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

See the documentation in `doc.txt` or run `begot help` for more details.
