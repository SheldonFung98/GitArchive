# GitArchive
Git Archives Command Line Management Tool

## Usage
```
ga = GitArchive(
    repo_path="SheldonFung98/GitArchive", # path to repo
    root="downloads", 
    token="your_github_token", 
    max_thread=8
)
ga.show()       # Show all releases.
release = ga[1] # Get the release at index 1.

# Download releases
ga.download(1)                      # Download releases at 1.
ga.download(name)                   # Download releases with name.
ga.download([1, 2, 3])              # Download releases at [1, 2, 3]
ga.download([name1, name2, name3])  # Download releases with names.
ga.download()                       # Download all releases.

# Create a new release in repo
ga.new_realease(
    name="new release name", 
    tag="v1.0.0", 
    desc="descriptions of the release", 
    files=["path2files"]
)
```