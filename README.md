# begot

[![](https://ci.solanolabs.com:443/solanolabs/begot/badges/155480.png)](https://ci.solanolabs.com:443/solanolabs/begot/suites/155480)

Begot is a Go dependency manager and build tool. It's similar to tools in the
same space like [Glide] and [Grapnel], and steals a few ideas from Blaze and
Bundler as well.

[Glide]: https://github.com/Masterminds/glide
[Grapnel]: https://github.com/eanderton/grapnel

**The main points:**

- A dependency file describes the dependencies of a project and can pin them to
  specific branches, tags, or commits.
- Instead of copying dependencies into a project repo, begot keeps them in a
  local cache that it manages.
- Users are encouraged to use free-form import paths instead of
  code-location-based import paths.
- Repo aliases make it easy to use forks of dependencies without any manual
  updating of import paths, even indirect dependencies.
- It works great with private repositories on GitHub or elsewhere that require
  ssh authentication.
- Begot acts as a wrapper for the go command.

**Here's a little more detail:**

Given a `Begotten` file with contents:

```
deps:
  gorilla/mux: github.com/gorilla/mux
```

`begot update` will fetch the master branch of that repo into its cache (stored
in `~/.cache/begot`) and create a `Begotten.lock` file that contains the head
commit id.

Then, `begot build` will ensure that all dependencies refered to by
`Begotten.lock` are present in the cache and reset to the right version, create
a special dependency workspace with symlinks to the cached repos, and run the go
command with a special `GOPATH`. Your Go code can `import "gorilla/mux"`.

Another developer can clone a repo with a `Begotten.lock` file and run `begot
fetch` to fetch all the dependencies without changing any pinned versions.

Begot rewrites imports within its cache to make things work right, but you never
see the rewrites and they never get committed anywhere.

If your dependencies have dependencies themselves, everything will work
transitively. If your dependencies use begot themselves, it'll check to make
sure all the locked versions agree and raise an error if they don't.

**For more details** and discussion of motivations and tradeoffs, see
[doc.txt](doc.txt).


Begot is released under a simplified BSD license.
