import sys

with open("scripts/pythia_sim_core.py", "r") as f:
    lines = f.readlines()

# Find the first def list_pythia_roots
start_idx = -1
for i, line in enumerate(lines):
    if line.startswith("    def list_pythia_roots(self) -> dict[str, Any]:"):
        start_idx = i
        break

# Find the second def list_pythia_roots
middle_idx = -1
if start_idx != -1:
    for i in range(start_idx + 1, len(lines)):
        if line.startswith("    def list_pythia_roots(self) -> dict[str, Any]:"):
            middle_idx = i
            break
        
# Actually, the file has it from lines 2283 down to 2343. Let's just find "    def search_pythia_examples"
end_idx = -1
for i in range(start_idx + 1, len(lines)):
    if line.startswith("    def search_pythia_examples(self, arguments: dict[str, Any]) -> dict[str, Any]:"):
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    new_content = """    def list_pythia_roots(self) -> dict[str, Any]:
        registry = load_registry(self.registry_path, plugin_root=self.plugin_root)
        roots = [inspect_root(entry) for entry in registry.roots.values()]
        return {
            "default_alias": registry.default_alias,
            "roots": roots,
        }

    def bootstrap_pythia(self, arguments: dict[str, Any]) -> dict[str, Any]:
        vendor_dir = self.state_root / "vendor"
        vendor_dir.mkdir(parents=True, exist_ok=True)
        pythia_dir = vendor_dir / PYTHIA_AUTO_ALIAS

        logs = []
        logs.append(f"Target directory: {pythia_dir}")

        if pythia_dir.exists() and (pythia_dir / "Makefile.inc").exists():
            logs.append("Pythia 8 is already installed.")
        else:
            if pythia_dir.exists():
                import shutil
                shutil.rmtree(pythia_dir)

            tarball_path = vendor_dir / f"{PYTHIA_AUTO_ALIAS}.tgz"
            logs.append(f"Downloading Pythia 8 from {PYTHIA_DOWNLOAD_URL}...")
            try:
                import urllib.request
                urllib.request.urlretrieve(PYTHIA_DOWNLOAD_URL, tarball_path)
            except Exception as exc:
                raise PythiaSimError(f"Failed to download Pythia 8: {exc}")

            logs.append("Extracting tarball...")
            try:
                import tarfile
                with tarfile.open(tarball_path, "r:gz") as tar:
                    tar.extractall(path=vendor_dir)
            except Exception as exc:
                raise PythiaSimError(f"Failed to extract tarball: {exc}")
            finally:
                if tarball_path.exists():
                    tarball_path.unlink()

            logs.append("Configuring Pythia 8...")
            config_result = _run_subprocess_capped(
                ["./configure"],
                cwd=pythia_dir,
                env=os.environ.copy(),
                timeout_sec=120,
                max_output_bytes=MAX_OUTPUT_BYTES,
            )
            logs.append(f"Configure stdout: {config_result.stdout}")
            if config_result.exit_code != 0:
                logs.append(f"Configure stderr: {config_result.stderr}")
                raise PythiaSimError(f"Configure failed with exit code {config_result.exit_code}.\\n" + "\\n".join(logs))

            logs.append("Compiling Pythia 8 (this may take a few minutes)...")
            make_result = _run_subprocess_capped(
                ["make", "-j4"],
                cwd=pythia_dir,
                env=os.environ.copy(),
                timeout_sec=600,
                max_output_bytes=MAX_OUTPUT_BYTES,
            )
            if make_result.exit_code != 0:
                logs.append(f"Make stderr: {make_result.stderr}")
                raise PythiaSimError(f"Make failed with exit code {make_result.exit_code}.\\n" + "\\n".join(logs))
            logs.append("Compilation successful.")

        registry_file = _candidate_registry_paths(
            plugin_root=self.plugin_root, env=os.environ, platform=_current_platform()
        )[0]
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        
        registry_data = {
            "default_alias": PYTHIA_AUTO_ALIAS,
            "roots": [
                {
                    "alias": PYTHIA_AUTO_ALIAS,
                    "path": str(pythia_dir),
                }
            ]
        }
        _write_json(registry_file, registry_data)
        logs.append(f"Updated registry at {registry_file}.")

        return {
            "ok": True,
            "alias": PYTHIA_AUTO_ALIAS,
            "path": str(pythia_dir),
            "registry_path": str(registry_file),
            "logs": "\\n".join(logs)
        }

"""
    lines[start_idx:end_idx] = [new_content]
    with open("scripts/pythia_sim_core.py", "w") as f:
        f.writelines(lines)
    print("Fixed duplication!")
else:
    print("Could not find start/end indices")
