**Exploration: hermes_cli/config.py**

Found 202 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`hermes_cli/config.py`** — calls(calls), ConfigIssue(instantiates), get_env_value(calls), get_config_path(calls), is_managed(calls), load_config(calls), get_env_path(calls), _model_assignment_text(calls), read_raw_config(calls), coerce_provider_id(calls), _warn_config_parse_failure(calls), load_env(calls), _expand_env_vars(calls), managed_error(calls), _secure_file(calls), +266 more

```python
693
694	def format_managed_message(action: str = "modify this Hermes installation") -> str:
695	    """Build a user-facing error for managed installs."""
696	    managed_system = get_managed_system() or "a package manager"
697	    return (
698	        f"Cannot {action}: this Hermes installation is managed by {managed_system}.\n"
699	        "Use your package manager to upgrade or reinstall Hermes."
700	    )
701
702	def managed_error(action: str = "modify configuration"):
703	    """Print user-friendly error for managed mode."""
704	    print(format_managed_message(action), file=sys.stderr)
705
706
707	# =============================================================================

... (gap) ...

719	    container.enable = true. It tells the host CLI to exec into the container
720	    instead of running locally.
721	    """
722	    if os.environ.get("HERMES_DEV") == "1":
723	        return None
724
725	    from hermes_constants import is_container
726	    if is_container():
727	        return None
728
729	    container_mode_file = get_hermes_home() / ".container-mode"
730
731	    try:
732	        info = {}

... (gap) ...

763
764	def get_config_path() -> Path:
765	    """Get the main config file path."""
766	    return get_hermes_home() / "config.yaml"
767
768	def get_env_path() -> Path:
769	    """Get the .env file path (for API keys)."""
770	    return get_hermes_home() / ".env"
771
772	def get_project_root() -> Path:
773	    """Get the project installation directory."""
774	    return Path(__file__).parent.parent.resolve()
775
776	def _resolve_hermes_uid_gid() -> tuple[Optional[int], Optional[int]]:
777	    """Read the HERMES_UID / HERMES_GID env vars set by Docker deployments.

... (gap) ...

790	    """
791	    if sys.platform == "win32":
792	        return None, None
793	    uid_str = os.environ.get("HERMES_UID", "").strip()
794	    gid_str = os.environ.get("HERMES_GID", "").strip()
795	    try:
796	        uid = int(uid_str) if uid_str else None
797	    except ValueError:

... (gap) ...

815	    directories created by :func:`ensure_hermes_home` on Docker deployments.
816	    See #34107.
817	    """
818	    uid, gid = _resolve_hermes_uid_gid()
819	    if uid is None and gid is None:
820	        return
821	    try:

... (gap) ...

850	    created at runtime by kanban workers don't land as root:root and block
851	    subsequent uid-mapped workers).
852	    """
853	    if is_managed():
854	        return
855	    try:
856	        mode_str = os.environ.get("HERMES_HOME_MODE", "").strip()
857	        mode = int(mode_str, 8) if mode_str else 0o700
858	    except ValueError:
859	        mode = 0o700
860	    try:
861	        os.chmod(path, mode)
862	    except (OSError, NotImplementedError):
863	        pass
864	    _chown_to_hermes_uid(path)
865
866
867	def _is_container() -> bool:
868	    """Detect if we're running inside a Docker/Podman/LXC container.
869
870	    When Hermes runs in a container with volume-mounted config files, forcing
871	    0o600 permissions breaks multi-process setups where the gateway and
872	    dashboard run as different UIDs or the volume mount requires broader
873	    permissions.
874	    """
875	    # Explicit opt-out
876	    if os.environ.get("HERMES_CONTAINER") or os.environ.get("HERMES_SKIP_CHMOD"):
877	        return True
878	    # Docker / Podman marker file
879	    if os.path.exists("/.dockerenv"):
880	        return True
881	    # LXC / cgroup-based detection
882	    try:

... (gap) ...

898	    Skipped in containers — Docker/Podman volume mounts often need broader
899	    permissions.  Set HERMES_SKIP_CHMOD=1 to force-skip on other systems.
900	    """
901	    if is_managed() or _is_container():
902	        return
903	    try:
904	        if os.path.exists(str(path)):
905	            os.chmod(path, 0o600)
906	    except (OSError, NotImplementedError):
907	        pass
908
909
910	def _ensure_default_soul_md(home: Path) -> None:
911	    """Seed a default SOUL.md into HERMES_HOME, upgrading legacy empty templates.
912
913	    First run: write DEFAULT_SOUL_MD. Existing installs whose SOUL.md is still
914	    the old comment-only scaffold (seeded by older install.sh / install.ps1 /
915	    docker images, which shadowed the runtime default) get upgraded in place to
916	    DEFAULT_SOUL_MD. A SOUL.md the user actually customized is never touched.
917	    """
918	    soul_path = home / "SOUL.md"
919	    if soul_path.exists():
920	        try:
921	            existing = soul_path.read_text(encoding="utf-8")
922	        except (OSError, UnicodeDecodeError):
923	            return
924	        if not is_legacy_template_soul(existing):
925	            return
926	        # Legacy empty template -> upgrade to the real default in place.
927	    soul_path.write_text(DEFAULT_SOUL_MD, encoding="utf-8")
928	    _secure_file(soul_path)
929
930
931	# Home paths whose directory skeleton has been created this process — see

... (gap) ...

949	    recreated on the next load, as before). Profile switches change
950	    ``get_hermes_home()`` and therefore re-run for the new path.
951	    """
952	    home = get_hermes_home()
953	    key = str(home)
954
955	    if key in _HERMES_HOME_ENSURED and home.is_dir():
956	        return
957	    # Named profiles must be created explicitly (e.g. ``hermes profile create``).
958	    # If a stale process keeps running after the profile was renamed/deleted,
959	    # silently mkdir-ing the old HERMES_HOME would resurrect an empty skeleton
960	    # and make the deleted profile reappear in Desktop/profile lists.
961	    if home.parent.name == "profiles" and not home.exists():
962	        raise FileNotFoundError(
963	            f"Named profile home does not exist: {home}. "
964	            "Create the profile explicitly before using it."
965	        )
966	    if is_managed():
967	        old_umask = os.umask(0o007)
968	        try:
969	            _ensure_hermes_home_managed(home)
970	        finally:
971	            os.umask(old_umask)
972	    else:
973	        home.mkdir(parents=True, exist_ok=True)
974	        _secure_dir(home)
975	        for subdir in (
976	            "cron", "sessions", "logs", "logs/curator", "memories",
977	            "pairing", "hooks", "image_cache", "audio_cache", "skills",
978	        ):
979	            d = home / subdir
980	            d.mkdir(parents=True, exist_ok=True)
981	            _secure_dir(d)
982	        _ensure_default_soul_md(home)
983
984	    _HERMES_HOME_ENSURED.add(key)
985
986
987	def _ensure_hermes_home_managed(home: Path):
988	    """Managed-mode variant: verify dirs exist (activation creates them), seed SOUL.md."""
989	    if not home.is_dir():
990	        raise RuntimeError(
991	            f"HERMES_HOME {home} does not exist."
992	        )
993	    for subdir in ("cron", "sessions", "logs", "memories"):
994	        d = home / subdir
995	        if not d.is_dir():
996	            raise RuntimeError(f"{d} does not exist.")
997	    # Curator reports dir is a sub-path of logs/; create it if missing.
998	    # In managed mode the activation script may not know about this subdir,
999	    # so we mkdir it ourselves (it's inside an already-secured logs/ dir).
1000	    (home / "logs" / "curator").mkdir(parents=True, exist_ok=True)
1001	    # Inside umask(0o007) scope — SOUL.md will be created as 0660
1002	    _ensure_default_soul_md(home)
1003
1004
1005	# =============================================================================

... (gap) ...

1044
1045	    # Check required vars
1046	    for var_name, info in REQUIRED_ENV_VARS.items():
1047	        if not get_env_value(var_name):
1048	            missing.append({"name": var_name, **info, "is_required": True})
1049
1050	    # Check optional vars (if not required_only)
1051	    if not required_only:
1052	        for var_name, info in OPTIONAL_ENV_VARS.items():
1053	            if not get_env_value(var_name):
1054	                missing.append({"name": var_name, **info, "is_required": False})
1055
1056	    return missing

... (gap) ...

1274	    Walks the DEFAULT_CONFIG tree at arbitrary depth and reports any keys
1275	    present in defaults but absent from the user's loaded config.
1276	    """
1277	    config = load_config()
1278	    missing = []
1279
1280	    def _check(defaults: dict, current: dict, prefix: str = ""):
1281	        for key, default_value in defaults.items():
1282	            if key.startswith('_'):
1283	                continue
1284	            full_key = key if not prefix else f"{prefix}.{key}"
1285	            if key not in current:
1286	                missing.append({
1287	                    "key": full_key,
1288	                    "default": default_value,
1289	                    "description": f"New config option: {full_key}",
1290	                })
1291	            elif isinstance(default_value, dict) and isinstance(current.get(key), dict):
1292	                _check(default_value, current[key], full_key)
1293
1294	    _check(DEFAULT_CONFIG, config)
1295	    return missing
1296
1297

... (gap) ...

6203	# An optional ``optional_env`` block surfaces non-required vars the same way
6204	# (e.g. allowlist, home channel).
6205
6206	_platform_plugin_env_vars_injected = False
6207
6208	# Core/provider declarations retain their authority over plugin metadata.
6209	_CORE_DECLARED_ENV_NAMES = frozenset(name.upper() for name in OPTIONAL_ENV_VARS)
6210	PLATFORM_SECRET_ENV_SUFFIXES = ("_TOKEN", "_SECRET", "_KEY", "_PASSWORD", "_JSON")
6211
6212
6213	def platform_manifest_secret_envs(home: Path | None) -> frozenset[str]:
6214	    """Read platform security declarations without importing plugin code.
6215
6216	    A known manifest that cannot be read or parsed cannot authorize a spawn.
6217	    User declarations stay home-scoped and cannot demote core credentials.
6218	    """
6219	    roots = [(Path(__file__).resolve().parents[1] / "plugins" / "platforms", True)]
6220	    if home is not None:
6221	        roots.extend(((Path(home) / "plugins" / "platforms", True), (Path(home) / "plugins", False)))
6222	    keys: set[str] = set()
6223	    try:
6224	        for root, platform_directory in roots:
6225	            if not root.exists():
6226	                continue
6227	            for child in root.iterdir():
6228	                if not child.is_dir():
6229	                    continue
6230	                path = child / "plugin.yaml"
6231	                if not path.exists():
6232	                    path = child / "plugin.yml"
6233	                if not path.exists():
6234	                    continue
6235	                with path.open("r", encoding="utf-8") as stream:
6236	                    manifest = fast_safe_load(stream)
6237	                if not isinstance(manifest, dict):
6238	                    raise ValueError("platform manifest must be a mapping")
6239	                if not platform_directory and manifest.get("kind") != "platform":
6240	                    continue
6241	                for field in ("requires_env", "optional_env"):
6242	                    entries = manifest.get(field, [])
6243	                    if entries is None:
6244	                        entries = []
6245	                    if not isinstance(entries, list):
6246	                        raise ValueError("platform env declaration must be a list")
6247	                    for entry in entries:
6248	                        meta = entry if isinstance(entry, dict) else {}
6249	                        name = meta.get("name") if meta else entry
6250	                        if not isinstance(name, str) or not name:
6251	                            raise ValueError("platform env declaration requires a name")
6252	                        for flag in ("password", "secret"):
6253	                            if meta.get(flag) is not None and not isinstance(meta[flag], bool):
6254	                                raise ValueError("platform security flag must be boolean")
6255	                        upper = name.upper()
6256	                        core = OPTIONAL_ENV_VARS.get(upper, {})
6257	                        if upper in _CORE_DECLARED_ENV_NAMES:
6258	                            if core.get("category") == "messaging" and core.get("password"):
6259	                                keys.add(upper)
6260	                            continue
6261	                        if meta.get("password") or meta.get("secret") or (
6262	                            meta.get("password") is not False
6263	                            and upper.endswith(PLATFORM_SECRET_ENV_SUFFIXES)
6264	                        ):
6265	                            keys.add(upper)
6266	    except Exception as exc:
6267	        raise RuntimeError("Cannot resolve platform manifest secret declaration") from exc
6268	    return frozenset(keys)
6269
6270
6271	def _inject_platform_plugin_env_vars() -> None:
6272	    """Populate OPTIONAL_ENV_VARS from bundled platform plugin manifests.
6273
6274	    Called once at module load time. Idempotent — repeated calls are no-ops.
6275	    Failures are swallowed so a malformed plugin.yaml can't break CLI import.
6276	    """
6277	    global _platform_plugin_env_vars_injected
6278	    if _platform_plugin_env_vars_injected:
6279	        return
6280	    _platform_plugin_env_vars_injected = True
6281	    try:
6282	        import yaml  # type: ignore
6283
6284	        # Resolve the bundled plugins dir from this file's location so the
6285	        # injector works regardless of CWD.
6286	        repo_root = Path(__file__).resolve().parents[1]
6287	        platforms_dir = repo_root / "plugins" / "platforms"
6288	        if not platforms_dir.is_dir():
6289	            return
6290	        for child in platforms_dir.iterdir():
6291	            if not child.is_dir():
6292	                continue
6293	            manifest_path = child / "plugin.yaml"
6294	            if not manifest_path.exists():
6295	                manifest_path = child / "plugin.yml"
6296	            if not manifest_path.exists():
6297	                continue
6298	            try:
6299	                with open(manifest_path, "r", encoding="utf-8") as f:
6300	                    manifest = fast_safe_load(f) or {}
6301	            except Exception:
6302	                continue
6303	            label = manifest.get("label") or manifest.get("name") or child.name
6304	            # Merge required + optional env var declarations.
6305	            entries = list(manifest.get("requires_env") or [])
6306	            entries.extend(manifest.get("optional_env") or [])
6307	            for entry in entries:
6308	                if isinstance(entry, str):
6309	                    name = entry
6310	                    meta: dict = {}
6311	                elif isinstance(entry, dict) and entry.get("name"):
6312	                    name = entry["name"]
6313	                    meta = entry
6314	                else:
6315	                    continue
6316	                if name in OPTIONAL_ENV_VARS:
6317	                    continue  # hardcoded entry wins (back-compat)
6318	                # Heuristic: anything named *TOKEN, *SECRET, *KEY, *PASSWORD
6319	                # is a password field unless explicitly overridden.
6320	                name_upper = name.upper()
6321	                is_secret = bool(meta.get("password") or meta.get("secret"))
6322	                if not is_secret and not meta.get("password") is False:
6323	                    is_secret = any(
6324	                        name_upper.endswith(suf)
6325	                        for suf in ("_TOKEN", "_SECRET", "_KEY", "_PASSWORD", "_JSON")
6326	                    )
6327	                OPTIONAL_ENV_VARS[name] = {
6328	                    "description": (
6329	                        meta.get("description")
6330	                        or f"{label} configuration"
6331	                    ),
6332	                    "prompt": meta.get("prompt") or name,
6333	                    "url": meta.get("url") or None,
6334	                    "password": is_secret,
6335	                    "category": meta.get("category") or "messaging",
6336	                }
6337	    except Exception:
6338	        pass
6339
6340
6341	# Eagerly inject so that platform plugin env vars show up in the setup wizard.
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
