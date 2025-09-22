# GitArchive
Git Archives Command Line Management Tool

## Usage
Initialize GitArchive
```
ga = GitArchive(
    repo_path="SheldonFung98/GitArchive", # path to repo
    root="downloads", 
    token="your_github_token", 
    max_thread=8
)
ga.show()       # Show all releases.
```

### Download all assets from releases
```
ga.download(1)                                  # Download releases at 1.
ga.download(name)                               # Download releases with name.
ga.download([1, 2, 3])                          # Download releases at [1, 2, 3]
ga.download([tag_name1, tag_name2, tag_name3])  # Download releases with names.
ga.download()                                   # Download all releases.
```

### Fine-grained release control
```
release = ga[1]         # Get the release at index 1.
release = ga[tag_name1] # Get the release with tag_name1.

release.download(asset_name)                    # Download asset with asset_name
release.download([asset_name1, asset_name2])    # Download multiple assets.
release.download(1)                             # Download asset at index 1
release.download([1, 2])                        # Download multiple assets.
release.download()                              # Download all assets.

```

### Create a new release in repo
```
ga.new_realease(
    name="new release name", 
    tag="v1.0.0", 
    desc="descriptions of the release", 
    files=["path2files"]
)
```