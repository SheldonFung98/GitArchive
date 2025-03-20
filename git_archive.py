from concurrent.futures import ThreadPoolExecutor, as_completed
from os.path import exists, join, getsize
from requests.auth import HTTPBasicAuth
from typing import Any, Sequence
from os import listdir, mkdir
from threading import Thread
from copy import deepcopy
from tqdm import tqdm
import pandas as pd
import argparse
import requests
import zipfile
import json
import sys


class RepoNotFoundError(Exception):
	def __init__(self, repo):
		self.message = f"{repo} not found or credentials not provided."
		super().__init__(self.message)

class RepoCredentialError(Exception):
	def __init__(self, repo):
		self.message = f"Bad credentials for {repo}."
		super().__init__(self.message)


class FileChunk:
	def __init__(self, file_path, chunk_size=4096):
		self.file_path = file_path
		self.chunk_size = chunk_size
		self.file_size = getsize(file_path)
		self.progress = 0
	
	def __iter__(self):
		file_size = 0
		total_length = getsize(self.file_path)
		t = tqdm(total=self.file_size, unit='B', unit_scale=True)
		with open(self.file_path, "rb") as file:
			while chunk := file.read(self.chunk_size):
				file_size += len(chunk)
				t.update(len(chunk))
				self.progress = file_size / self.file_size
				yield chunk
		t.close()
	
	def __len__(self):
		return self.file_size

class Transfer(Thread):
	TRANSFER_TYPES = ["download", "upload"]

	def __init__(self, url, file_path, params, ttype="download", chunk_size=4096):
		assert ttype in Transfer.TRANSFER_TYPES, "type should be one of {}".format(Transfer.TRANSFER_TYPES)
		self.trasfer = self._download if ttype == "download" else self._upload
		if ttype == "upload":
			self.file = FileChunk(file_path, chunk_size)
		self.url = url
		self.file_path = file_path
		self.params = params
		self.chunk_size = chunk_size
		self.progress = 0
		self.done = False
		super().__init__()
	
	def _download(self):
		file_name = self.file_path.split("/")[-1]
		response = requests.get(self.url, **self.params)
		total_length = response.headers.get('content-length')
		with open(self.file_path, "wb") as file:
			dl_length, total_length = 0, int(total_length)
			t = tqdm(total=total_length, unit='B', unit_scale=True)
			for data in response.iter_content(chunk_size=self.chunk_size):
				dl_length += len(data)
				t.update(len(data))
				file.write(data)
				self.progress = dl_length / total_length
			t.close()
		self.done = True

	def _upload(self):
		file_name = self.file_path.split("/")[-1]
		params = deepcopy(self.params)
		params["data"] = self.file
		url = f"{self.url}?name={file_name}"
		upload_response = requests.post(url, **params)
		if upload_response.status_code not in [200, 201]:
			raise Exception(f"Failed to upload {file_name}: {upload_response.json()}")
		self.done = True
	
	def get_filepath(self):
		return self.file_path
	
	def get_progress(self):
		if ttype == "upload":
			return self.file.progress
		elif ttype == "download":
			return self.progress

	def run(self):
		while not self.done:
			try:
				self.trasfer()
			except Exception as e:
				print("Error occur: {}".format(e))
				print("Retry transfer {}.".format(self.url))
				continue

class DynamicBatchExecute:
	def __init__(self, threads, max_threads=8):
		self.threads = threads
		self.max_threads = max_threads
		self.executor = None
		self.futures = []

	def start(self, non_blocking=False):
		self.executor = ThreadPoolExecutor(max_workers=self.max_threads)
		self.futures = {self.executor.submit(thread.run): thread for thread in self.threads}
		if not non_blocking:
			self.wait()

	def wait(self):
		for future in as_completed(self.futures):
			thread = self.futures[future]
			try:
				future.result()
			except Exception as exc:
				print(f'{thread} generated an exception: {exc}')
		self.executor.shutdown()

	def get_progress(self):
		return sum([thread.get_progress() for thread in self.threads]) / len(self.threads)

class Release:
	FILE_SIZE_FORMATS = ["B", "KB", "MB", "GB"]

	def __init__(self, info, root, token=None, file_size_format="MB", max_threads=8):
		assert file_size_format in Release.FILE_SIZE_FORMATS, "file_size_format should be one of {}".format(Release.FILE_SIZE_FORMATS)
		self.file_size_format = file_size_format
		self.url                = info["url"]
		self.assets_url         = info["assets_url"]
		self.upload_url         = info["upload_url"]
		self.html_url           = info["html_url"]
		self.id                 = info["id"]
		self.author             = info["author"]
		self.node_id            = info["node_id"]
		self.tag_name           = info["tag_name"]
		self.target_commitish   = info["target_commitish"]
		self.name               = info["name"]
		self.draft              = info["draft"]
		self.prerelease         = info["prerelease"]
		self.created_at         = info["created_at"]
		self.published_at       = info["published_at"]
		self.assets_df          = pd.DataFrame(info["assets"])
		self.tarball_url        = info["tarball_url"]
		self.zipball_url        = info["zipball_url"]
		self.body               = info["body"]
		self.root               = root
		self.max_threads		= max_threads

		self.assets_df["size"] = self.assets_df["size"].apply(
			lambda x: "{} {}".format(self._format_size(x), self.file_size_format)
		)

		self.download_params = dict(
			allow_redirects=True, 
			stream=True,
			headers={"Accept": "application/octet-stream"}
		)
		self.progress = 0
		if token is not None:
			self.download_params["auth"] = HTTPBasicAuth("", token)
	
	def get_downloaded_paths(self):
		return self.downloaded_paths

	def _format_size(self, size):
		if self.file_size_format == "KB":
			size = size/1024
		elif self.file_size_format == "MB":
			size = size/1024/1024
		elif self.file_size_format == "GB":
			size = size/1024/1024/1024
		return round(size, 2)
	
	def __str__(self):
		msg = f"name: {self.name} author: {self.author} \n Description:\n{self.body}"
		assets = self.assets_df[["name", "size"]]
		msg += "\nAssets:\n" + str(assets)
		return msg
	
	def _download(self, assets):
		download_threads = []
		for _, asset in assets.iterrows():
			download_url = asset["url"]
			file_name = asset["name"]
			file_path = join(self.root, file_name)
			if exists(file_path): continue # Do not redownload file.
			download_threads.append(Transfer(download_url, file_path, self.download_params))
		return download_threads

	def download(self, index=None, non_blocking=False):
		if not exists(self.root):
			mkdir(self.root)
		if index is None:
			target_assert = self.assets_df
		elif isinstance(index, int):
			target_assert = self.assets_df.iloc[index]
		elif isinstance(index, str):
			target_assert = self.assets_df[self.assets_df["name"] == index]
		elif isinstance(index, (list, tuple)):
			if isinstance(index[0], int):
				target_assert = self.assets_df.iloc[index]
			elif isinstance(index[0], str):
				target_assert = self.assets_df[self.assets_df["name"] == index]
			else:
				raise ValueError("index list should contains int or str.")
		else:
			raise ValueError("index should be int, str, list or tuple.")
		dl_threads = self._download(target_assert)

		if non_blocking:
			return dl_threads
		else:
			batch_execute(dl_threads, self.max_threads)
		return [thread.get_filepath() for thread in dl_threads]

class GitArchive:
	GITHUB_API = "https://api.github.com"
	DEFAULT_HEADER = dict(
		Accept="application/vnd.github.v3.raw",
	)
	DOWNLOAD_FOLDER_NAME = "downloads"
	TOKEN_FN = "github.tk"

	def __init__(self, repo_path, root, token=None, max_threads=8, token_autosave=True):
		self.root = root
		self.repo_path = repo_path
		self.headers = deepcopy(GitArchive.DEFAULT_HEADER)
		self.token = self.token_io(token)
		if self.token:
			self.headers["Authorization"] = "token {}".format(self.token)
		self.max_threads = max_threads
		self.url = "{}/repos/{}/releases".format(GitArchive.GITHUB_API, self.repo_path)
		self.releases_df = self._getReleases()
	
	def token_io(self, token):
		if token is None:
			if exists(GitArchive.TOKEN_FN):
				with open(GitArchive.TOKEN_FN, "r") as tk_file:
					token = tk_file.read()
		else:
			with open(GitArchive.TOKEN_FN, "w") as tk_file:
				tk_file.write(token)
		return token

	def _getReleases(self):
		req = requests.get(self.url, headers=self.headers)
		if req.status_code == 404:
			raise RepoNotFoundError(self.repo_path)
		elif req.status_code == 401:
			raise RepoCredentialError(self.repo_path)
		releases_df = pd.DataFrame(json.loads(req.content.decode("utf-8")))
		releases_df['author'] = releases_df['author'].apply(lambda x: x['login'])
		return releases_df
	
	def releases(self):
		return self.releases_df
	
	def show(self):
		print(self)

	def __str__(self):
		return str(self.releases_df[["name", "author", "published_at", "tag_name"]])
	
	def __len__(self):
		return len(self.releases_df)

	def __getitem__(self, index: int):
		return Release(self.releases_df.iloc[index], self.root, self.token)

	def download(self, index: Sequence[str] | Sequence[int] | str | int | None = None, non_blocking=False):
		"""Download releases.
		Args:
			index (Sequence[str] | Sequence[int] | str | int | None, optional): index of releases to download. Defaults to None.

			index can be:
			- None: download all releases.
			- int: download the release at index.
			- str: download the release with tag name.
			- list: download the releases at index list or tag name list.

		Returns:
			_type_: _description_
		"""
		if isinstance(index, int):
			download_df = self.releases_df.iloc[[index]]
		elif isinstance(index, str):
			download_df = self.releases_df[self.releases_df["tag_name"] == index] if index else self.releases_df
		elif isinstance(index, (list, tuple)):
			index = list(index)
			if isinstance(index[0], int):
				download_df = self.releases_df.iloc[index]
			elif isinstance(index[0], str):
				download_df = self.releases_df[self.releases_df["tag_name"].isin(index)]
			else:
				raise ValueError("index list should contains int or str.")
		elif index is None:
			download_df = self.releases_df
		else:
			raise ValueError("index should be int, str, list or tuple.")
		if download_df.empty:
			print("Nothing to download.")
		threads = []

		releases = [Release(asset, self.root, self.token, max_threads=self.max_threads) for ind, asset in download_df.iterrows()]
		dl_threads = [d for r in releases for d in r.download(non_blocking=True)]
		batch_exe = DynamicBatchExecute(dl_threads, self.max_threads)
		if non_blocking:
			return batch_exe
		else:
			batch_exe.start()
			return [t.get_filepath() for t in dl_threads] 

	def new_realease(self, name: str, tag: str, desc: str, files: Sequence[str], non_blocking=False):
		"""
		Create a new release and upload files to it.
		Args:
			name (str): The name of the release.
			tag (str): The tag name of the release.
			desc (str): Description of the release.
			files (Sequence[str]): List of file paths to upload.
		"""
		data = dict(tag_name=tag, name=name, body=desc, draft=False, prerelease=False)
		headers = deepcopy(self.headers)
		response = requests.post(self.url, headers=headers, json=data)
		
		if response.status_code not in [200, 201]:
			raise Exception(f"Failed to create release: {response.json()}")
		
		release_info = response.json()
		upload_url = release_info["upload_url"].split("{?name,label}")[0]
		
		headers["Content-Type"] = "application/octet-stream"
		params = dict(headers=headers, stream=True)
		ul_threads = [Transfer(upload_url, file, params, ttype="upload") for file in files]
		batch_exe = DynamicBatchExecute(ul_threads, self.max_threads)
		if non_blocking:
			return batch_exe
		else:
			batch_exe.start()
			return [t.get_filepath() for t in ul_threads] 

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Git Archives Command Line Management Tool.")
	parser.add_argument("repo", type=str, help="repo path, i.e., SheldonFung98/GitArchive")
	parser.add_argument("-t", default=None, type=str, help="github token.")
	parser.add_argument("-v", default=None, type=str, help="release version.")
	parser.add_argument("-root", default='downloads', type=str, help="Download root folder.")
	parser.add_argument("--all", action='store_true', help="Download everything.")
	parser.add_argument("-max_thread", default=8, type=int, help="Max threads for downloading.")
	parser.add_argument("--new", action='store_true', help="Max threads for downloading.")
	parser.add_argument("-name", default=None, type=str, help="Release name.")
	parser.add_argument("-tag", default=None, type=str, help="Release tag.")
	parser.add_argument("-desc", default=None, type=str, help="Release body.")
	parser.add_argument("-folder", default=None, type=str, help="Folder to upload.")

	args = parser.parse_args()
	ga = GitArchive(args.repo, args.root, args.t, args.max_thread)
	ga.show()
	release = ga[1]
	print(release)
	if args.all:
		download_paths = ga.download()
		print(download_paths)
	if args.new:
		files = [join(args.folder, f) for f in listdir(args.folder)]
		upload_paths = ga.new_realease(args.name, args.tag, args.desc, files)
		print(upload_paths)
