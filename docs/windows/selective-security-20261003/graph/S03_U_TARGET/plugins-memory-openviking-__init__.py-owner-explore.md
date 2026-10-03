**Exploration: plugins/memory/openviking/__init__.py**

Found 253 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/memory/openviking/__init__.py`** — calls(calls), get(calls), _clean_config_value(calls), _token_units(calls), _ensure_client(calls), _unwrap_result(calls), _normalize_openviking_url(calls), _emit_runtime(calls), post(calls), references(references), _message_text(calls), _status_code_from_error(calls), _format_openviking_exception(calls), _load_hermes_openviking_config(calls), _settings_tuple(calls), +388 more

```python
177
178
179	def _status_code_from_error(error: Exception) -> Optional[int]:
180	    if isinstance(error, _OpenVikingHTTPError):
181	        return error.status_code
182	    return getattr(getattr(error, "response", None), "status_code", None)
183
184
185	def _format_openviking_exception(error: Exception) -> str:
186	    return _sanitize_openviking_error_message(str(error), _status_code_from_error(error))
187
188
189	def _derive_openviking_user_text(content: Any) -> str:
190	    """Strip Hermes slash-skill scaffolding before sending content to OpenViking
191	    (MemoryManager already does this for the fan-out; kept for direct hook callers)."""
192	    return extract_user_instruction_from_skill_message(content) or ""
193
194
195	def _preview(value: Any, limit: int = 160) -> str:
196	    text = ("" if value is None else str(value)).replace("\n", "\\n")
197	    return text[:limit] + "..." if len(text) > limit else text
198
199
200	# atexit safety net: commit pending sessions even if shutdown_memory_provider
201	# never runs (gateway crash, exception in the session expiry watcher, ...).
202	# One entry per Hermes home: a multiplexed gateway initializes a provider per profile and every
203	# one of them holds pending sessions worth committing, not just the last to initialize.
204	_active_providers_by_home: Dict[str, "OpenVikingMemoryProvider"] = {}
205
206
207	def _atexit_commit_sessions():
208	    providers = list(_active_providers_by_home.values())
209	    _active_providers_by_home.clear()
210	    for provider in providers:
211	        try:
212	            with suppress(Exception):  # best-effort at shutdown time
213	                provider.on_session_end([])
214	        finally:
215	            # ``finally`` (as on main): the run lock is released even when on_session_end
216	            # dies of a BaseException (KeyboardInterrupt during atexit).
217	            with suppress(Exception):
218	                provider._release_run_lock()
219
220
221	atexit.register(_atexit_commit_sessions)

... (gap) ...

241	        # omit these headers unless OpenViking explicitly asks for them (retry).
242	        # Tenant identity is a profile .env value: scope-read so a multiplexed
243	        # secondary never writes into the default profile's tenant.
244	        self._account = account or get_secret("OPENVIKING_ACCOUNT", "") or "default"
245	        self._user = user or get_secret("OPENVIKING_USER", "") or "default"
246	        self._agent = agent if agent is not None else (get_secret("OPENVIKING_AGENT", "") or _DEFAULT_AGENT)
247	        self._httpx = _get_httpx()
248	        if self._httpx is None:
249	            raise ImportError("httpx is required for OpenViking: pip install httpx")
250

... (gap) ...

272	        return getattr(exc, "status_code", None) in (None, 400)
273
274	    def _multipart_headers(self, *, include_tenant: bool | None = None) -> dict:
275	        headers = self._headers(include_tenant=include_tenant)
276	        headers.pop("Content-Type", None)
277	        return headers
278
279	    def _send_with_trusted_identity_retry(self, send, *, multipart: bool = False) -> dict:
280	        build = self._multipart_headers if multipart else self._headers
281	        try:
282	            return self._parse_response(send(build()))
283	        except Exception as exc:
284	            if not self._api_key or not self._needs_trusted_identity_retry(exc):
285	                raise
286	            return self._parse_response(send(build(include_tenant=True)))
287
288	    def _parse_response(self, resp) -> dict:
289	        data = None
290	        with suppress(Exception):
291	            data = resp.json()
292	        error = data.get("error") if isinstance(data, dict) else None
293	        if resp.status_code >= 400:
294	            message = _sanitize_openviking_error_message(getattr(resp, "text", ""), resp.status_code)
295	            if isinstance(error, dict):
296	                raise _OpenVikingHTTPError(f"{error.get('code', 'HTTP_ERROR')}: {error.get('message', message)}", resp.status_code)
297	            if isinstance(data, dict) and data.get("status") == "error":
298	                raise _OpenVikingHTTPError(str(data), resp.status_code)
299	            raise _OpenVikingHTTPError(message or f"HTTP {resp.status_code}", resp.status_code)
300	        if isinstance(data, dict) and data.get("status") == "error":
301	            if isinstance(error, dict):
302	                raise RuntimeError(f"{error.get('code', 'OPENVIKING_ERROR')}: {error.get('message', '')}")
303	            raise RuntimeError(str(data))
304	        return {} if data is None else data
305
306	    def _request(self, method: str, path: str, kwargs: dict) -> dict:
307	        timeout = kwargs.pop("timeout", _TIMEOUT)
308	        fn = getattr(self._httpx, method)
309	        return self._send_with_trusted_identity_retry(lambda headers: fn(f"{self._endpoint}{path}", headers=headers, timeout=timeout, **kwargs))
310
311	    def get(self, path: str, **kwargs) -> dict:
312	        return self._request("get", path, kwargs)
313
314	    def post(self, path: str, payload: dict = None, **kwargs) -> dict:
315	        return self._request("post", path, {**kwargs, "json": payload or {}})
316
317	    def delete(self, path: str, **kwargs) -> dict:
318	        return self._request("delete", path, kwargs)
319
320	    def upload_temp_file(self, file_path: Path) -> str:
321	        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
322
323	        def _send(headers):
324	            with file_path.open("rb") as f:
325	                return self._httpx.post(f"{self._endpoint}/api/v1/resources/temp_upload",
326	                                        files={"file": (file_path.name, f, mime_type)}, headers=headers, timeout=_TIMEOUT)
327
328	        temp_file_id = self._send_with_trusted_identity_retry(_send, multipart=True).get("result", {}).get("temp_file_id", "")
329	        if not temp_file_id:
330	            raise RuntimeError("OpenViking temp upload did not return temp_file_id")
331	        return temp_file_id
332
333	    def health(self) -> bool:
334	        with suppress(Exception):
335	            return _probe_openviking_identity(self)[0] in _OPENVIKING_IDENTIFIED_STATES
336	        return False
337
338	    def _anonymous_json(self, path: str) -> dict:
339	        """Probe server identity without disclosing credentials or tenant IDs."""
340	        return self._parse_response(self._httpx.get(f"{self._endpoint}{path}", headers={"Accept": "application/json"}, timeout=3.0))
341
342	    def health_payload(self) -> dict:
343	        """``GET /health``, anonymous first so credentials never reach an unknown host.
344	        Hosted OpenViking requires auth on /health: when an API key is configured and the
345	        anonymous call gets 401/403, retry once with the key (no tenant headers).
346
347	        Prefer an anonymous probe so credentials are never sent to an unknown host during identity checks.
348	        See #78410.
349	        """
350	        try:
351	            return self._anonymous_json("/health")
352	        except _OpenVikingHTTPError as exc:
353	            if not self._api_key or _status_code_from_error(exc) not in {401, 403}:
354	                raise
355	            return self._parse_response(self._httpx.get(f"{self._endpoint}/health", headers=self._headers(include_tenant=False), timeout=3.0))
356
357	    def openapi_payload(self) -> dict:
358	        return self._anonymous_json("/openapi.json")
359
360	    def validate_auth(self) -> dict:  # authenticated access, no mutation
361	        return self.get("/api/v1/system/status")
362
363	    def validate_root_access(self) -> dict:  # ROOT access via a read-only admin endpoint
364	        return self.get("/api/v1/admin/accounts")
365
366
367	# -- Tool schemas -----------------------------------------------------------
368
369	def _tool_schema(name: str, description: str, properties: dict, required: list) -> dict:
370	    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}
371
372
373	def _str(description: str, **extra) -> dict:

... (gap) ...

463	    reports no user. Callers may fall back to a configured value for that one operation but
464	    must not cache an unverified identity — a later probe can succeed."""
465	    try:
466	        status = client.get("/api/v1/system/status", **({"timeout": timeout} if timeout is not None else {}))
467	    except Exception:
468	        logger.debug("OpenViking user-space probe failed; using configured fallback", exc_info=True)
469	        return None
470	    return str(((status or {}).get("result") or {}).get("user") or "").strip() or None
471
472
473	def _zip_directory(dir_path: Path) -> Path:

... (gap) ...

483	            try:
484	                resolved = file_path.resolve()
485	                resolved.relative_to(root)
486	                raise_if_read_blocked(str(resolved))
487	            except ValueError:
488	                continue
489	            zipf.write(file_path, arcname=str(file_path.relative_to(dir_path)).replace("\\", "/"))
490	    return zip_path
491
492

... (gap) ...

505	        return None, "viking_forget requires an exact URI without query or fragment"
506	    if uri.endswith("/") or not uri.endswith(".md"):
507	        return None, "viking_forget only deletes concrete .md memory files"
508	    parts = [part for part in uri[len("viking://") :].split("/") if part]
509	    # ``memories`` segment index for the user / user-uid / peer / uid-peer layouts.
510	    memories_idx = next((idx for idx, peer_at in ((1, None), (2, None), (3, 1), (4, 2))
511	                         if parts[:1] == ["user"] and len(parts) > idx and parts[idx] == "memories" and (peer_at is None or parts[peer_at] == "peers")), None)
512	    if memories_idx is None or len(parts) < memories_idx + 2:
513	        return None, "viking_forget only deletes user memory file URIs"
514	    if uri.rsplit("/", 1)[-1] in _GENERATED_MEMORY_SUMMARY_FILENAMES:
515	        return None, "viking_forget cannot delete generated memory summary files"
516	    return uri, None
517
518
519	def _is_local_path_reference(value: str) -> bool:
520	    if not value or "\n" in value or "\r" in value or value.startswith(_REMOTE_RESOURCE_PREFIXES):
521	        return False
522	    if _is_windows_absolute_path(value):
523	        return True
524	    return value.startswith(("/", "./", "../", "~/", ".\\", "..\\", "~\\")) or "/" in value or "\\" in value
525
526
527	def _clean_config_value(value: Any) -> str:
528	    return value.strip() if isinstance(value, str) else ""
529
530
531	def _openviking_endpoint_label(value: Any) -> str:
532	    """Credential-free endpoint label for logs and UI."""
533	    raw = _clean_config_value(value)
534	    if not raw:
535	        return "<empty endpoint>"
536	    try:

... (gap) ...

552
553
554	def _resolve_ovcli_config_path(config_path: str = "") -> Path:
555	    chosen = os.environ.get(_OVCLI_CONFIG_ENV, "").strip() or config_path
556	    return Path(chosen).expanduser() if chosen else _default_ovcli_config_path()
557
558
559	def _load_ovcli_config(path: Optional[Path] = None) -> dict:
560	    config_path = path or _resolve_ovcli_config_path()
561	    if not config_path.exists():
562	        return {}
563	    with config_path.open(encoding="utf-8-sig") as f:
564	        data = json.load(f)
565	    if not isinstance(data, dict):
566	        raise ValueError(f"OpenViking CLI config must be a JSON object: {config_path}")
567	    return data
568
569
570	def _connection_values_from_ovcli(data: dict) -> dict:
571	    endpoint_value = _clean_config_value(data.get("url"))
572	    api_key = _clean_config_value(data.get("api_key")) or _clean_config_value(data.get("root_api_key"))
573	    root_api_key = _clean_config_value(data.get("root_api_key"))
574	    send_identity = not api_key or api_key == root_api_key  # user keys derive tenant server-side
575	    return {
576	        # No URL -> no endpoint; the resolver continues to config.yaml, then the default.
577	        "endpoint": _normalize_openviking_url(endpoint_value) if endpoint_value else "",
578	        "api_key": api_key,
579	        "root_api_key": root_api_key,
580	        "account": _clean_config_value(data.get("account") or data.get("account_id")) if send_identity else "",
581	        "user": _clean_config_value(data.get("user") or data.get("user_id")) if send_identity else "",
582	        "agent": _clean_config_value(data.get("actor_peer_id") or data.get("agent_id")),
583	    }
584
585

... (gap) ...

612	    on every access (Dashboard / ``/reload``), so slow DNS lookups stay off the hot path."""
613	    from tools.url_safety import is_always_blocked_url
614
615	    return is_always_blocked_url(candidate)
616
617
618	def _normalize_openviking_url(url: str) -> str:
619	    trimmed = _clean_config_value(url).rstrip("/")
620	    if not trimmed:
621	        return _DEFAULT_ENDPOINT
622	    lower = trimmed.lower()

... (gap) ...

636	        if parsed.username or parsed.password or parsed.query or parsed.fragment:
637	            raise ValueError("OpenViking endpoints cannot contain user info, query parameters, or fragments.")
638	    except ValueError as exc:
639	        raise _OpenVikingEndpointError(f"Invalid OpenViking endpoint {_openviking_endpoint_label(candidate)}: {exc}") from exc
640
641	    # Local/LAN self-host stays allowed; reject cloud-metadata floors so a poisoned
642	    # endpoint cannot SSRF via memory sync. Never silently substitute localhost for
643	    # an unsafe endpoint — that could forward credentials to the wrong deployment.
644	    try:
645	        blocked = _openviking_endpoint_is_always_blocked(candidate)
646	    except Exception as exc:
647	        logger.debug("OpenViking endpoint safety validation failed", exc_info=True)
648	        raise _OpenVikingEndpointError("OpenViking endpoint safety validation failed; Hermes refused the connection.") from exc
649	    if blocked:
650	        raise _OpenVikingEndpointError(
651	            f"OpenViking endpoint {_openviking_endpoint_label(candidate)} targets a blocked metadata address."
652	        )
653	    return candidate
654
655
656	def _probe_openviking_identity(client: _VikingClient) -> tuple[str, Any]:
657	    """Identify modern or legacy OpenViking before any authenticated request.
658	    -> ("modern" | "legacy" | "legacy-unverified" | "unhealthy" | "invalid", health).
659	    Modern = documented status/healthy/version contract; legacy = status-only (<= 0.2.6),
660	    which must be confirmed via the anonymous OpenAPI title."""
661	    health = client.health_payload()
662	    if isinstance(health, dict) and health.get("healthy") is False:
663	        return "unhealthy", health
664	    if not isinstance(health, dict) or health.get("status") != "ok":
665	        return "invalid", health
666	    if health.get("healthy") is True and isinstance(health.get("version"), str) and health["version"].strip():
667	        return "modern", health
668	    if "healthy" in health or "version" in health:
669	        return "invalid", health
670	    try:
671	        info = client.openapi_payload().get("info")
672	        verified = isinstance(info, dict) and info.get("title") == "OpenViking API"
673	    except Exception:
674	        logger.debug("Legacy OpenViking OpenAPI identity probe failed", exc_info=True)
675	        verified = False
676	    return ("legacy" if verified else "legacy-unverified"), health
677
678
679	def _load_profile(path: Path, *, source: str, name: str) -> Optional[_OvcliProfile]:
680	    try:
681	        values = _connection_values_from_ovcli(_load_ovcli_config(path))
682	    except Exception as e:
683	        logger.warning("Skipping invalid OpenViking CLI config %s: %s", path, _format_openviking_exception(e))
684	        return None
685	    return _OvcliProfile(source=source, name=name, path=path, values=values)
686
687
688	def _profile_identity(path: Path) -> str:
689	    try:
690	        return str(path.expanduser().resolve())
691	    except OSError:
692	        return str(path.expanduser())
693
694
695	def _discover_ovcli_profiles() -> list[_OvcliProfile]:
696	    """env-pointed config, then saved ``ovcli.conf.<name>`` files, then the active
697	    ``ovcli.conf`` — which is only listed on its own when no saved profile has
698	    identical connection values and nothing else was found."""
699	    profiles: list[_OvcliProfile] = []
700	    seen_paths: set[str] = set()
701
702	    def add(path: Path, *, source: str, name: str) -> None:
703	        identity = _profile_identity(path)
704	        if path.is_file() and identity not in seen_paths and (profile := _load_profile(path, source=source, name=name)) is not None:
705	            seen_paths.add(identity)
706	            profiles.append(profile)
707
708	    env_path = os.environ.get(_OVCLI_CONFIG_ENV, "").strip()
709	    if env_path:
710	        add(Path(env_path).expanduser(), source="env", name=_OVCLI_CONFIG_ENV)
711
712	    active_path = _default_ovcli_config_path()
713	    active_profile = _load_profile(active_path, source="active", name="active") if active_path.exists() else None
714
715	    config_dir = _default_ovcli_config_path().parent
716	    saved_start = len(profiles)
717	    if config_dir.exists():
718	        for path in sorted(config_dir.iterdir(), key=lambda item: item.name):
719	            name = path.name.removeprefix(_OVCLI_SAVED_PREFIX)
720	            if path.is_file() and name != path.name and name != "bak" and _is_valid_ovcli_profile_name(name):
721	                add(path, source="saved", name=name)
722
723	    if active_profile is not None:
724	        marked_active = False
725	        for idx in range(saved_start, len(profiles)):
726	            if profiles[idx].source == "saved" and profiles[idx].values == active_profile.values:
727	                profiles[idx] = replace(profiles[idx], is_active=True)
728	                marked_active = True
729	                break
730	        if not marked_active and not profiles and _profile_identity(active_profile.path) not in seen_paths:
731	            profiles.append(active_profile)
732	    return profiles
733
734
735	def _is_local_openviking_url(value: str) -> bool:
736	    try:
737	        candidate = _normalize_openviking_url(value)
738	    except _OpenVikingEndpointError:
739	        return False
740	    parsed = urlparse(candidate)
741	    return parsed.scheme.lower() == "http" and (parsed.hostname or "").lower() in _LOCAL_OPENVIKING_HOSTS
742
743
744	def _load_hermes_openviking_config() -> dict:
745	    try:
746	        from hermes_cli.config import load_config_readonly
747
748	        config = load_config_readonly()
749	        memory_config = config.get("memory", {}) if isinstance(config, dict) else {}
750	        provider_config = memory_config.get("openviking", {}) if isinstance(memory_config, dict) else {}
751	        return dict(provider_config) if isinstance(provider_config, dict) else {}
752	    except Exception:
753	        return {}
754
755
756	def _ovcli_values_for(provider_config: dict) -> dict:
757	    """Connection values from the linked ovcli profile, or {} when none is linked."""
758	    if not provider_config.get("use_ovcli_config"):
759	        return {}
760	    ovcli_path = _resolve_ovcli_config_path(str(provider_config.get("ovcli_config_path") or ""))
761	    return _connection_values_from_ovcli(_load_ovcli_config(ovcli_path))
762
763
764	def _resolve_connection_settings(provider_config: Optional[dict] = None) -> dict:
765	    """Layering: env -> linked ovcli profile -> config.yaml -> built-in default.
766	    An env account/user (even empty) is authoritative; the secret api_key never
767	    comes from config.yaml. Every env read goes through the profile secret scope:
768	    under multiplexing ``os.environ`` is the DEFAULT profile's .env, and a raw read
769	    would spend its key and tenant on behalf of a secondary profile."""
770	    provider_config = dict(provider_config or {})
771	    ovcli_values = _ovcli_values_for(provider_config)
772
773	    def layered(key: str, default: str = "", *, env_authoritative: bool = False) -> str:
774	        env = get_secret(f"OPENVIKING_{key.upper()}")
775	        if env is not None:
776	            env = env.strip()
777	            if env_authoritative:
778	                return env
779	        return env or ovcli_values.get(key) or _clean_config_value(provider_config.get(key)) or default
780
781	    api_key_env = get_secret("OPENVIKING_API_KEY")
782	    return {
783	        "endpoint": _normalize_openviking_url(layered("endpoint", _DEFAULT_ENDPOINT)),
784	        "api_key": api_key_env.strip() if api_key_env is not None else ovcli_values.get("api_key", ""),
785	        "account": layered("account", env_authoritative=True),
786	        "user": layered("user", env_authoritative=True),
787	        "agent": layered("agent", _DEFAULT_AGENT),
788	    }
789
790
791	def _secure_secret_file(path: Path, *, create: bool = False) -> None:
792	    """chmod 0600 a secret-bearing file; with ``create`` also pre-create it BEFORE writing
793	    (write-then-chmod leaves a window where the fresh file is world-readable under the umask)."""
794	    try:
795	        if create and not path.exists():
796	            os.close(os.open(str(path), os.O_CREAT | os.O_WRONLY, 0o600))
797	        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
798	    except OSError as e:
799	        logger.debug("Could not %s secret file %s: %s", "pre-create" if create else "restrict permissions on", path, e)
800
801
802	def _env_line_safe(value: Any) -> str:
803	    """Strip CR/LF/NUL so a value can only occupy its single ``KEY=VALUE`` line — an
804	    embedded line break would be re-parsed as a separate variable (secret injection)."""
805	    text = value if isinstance(value, str) else str(value)
806	    return "".join(text.replace("\x00", "").splitlines())
807
808
809	def _write_env_vars(env_path: Path, env_writes: dict, remove_keys: tuple[str, ...] = ()) -> None:
810	    env_path.parent.mkdir(parents=True, exist_ok=True)
811	    remove_set = set(remove_keys) - set(env_writes)
812	    # utf-8-sig + surrogateescape: a Windows editor may leave a BOM (breaks the
813	    # first key match) or save cp1252; round-trip undecodable bytes unchanged so
814	    # updating one credential cannot corrupt an unrelated value.
815	    existing_lines = env_path.read_text(encoding="utf-8-sig", errors="surrogateescape").splitlines() if env_path.exists() else []
816	    updated_keys = set()
817	    new_lines = []
818	    for line in existing_lines:
819	        key_match = line.split("=", 1)[0].strip() if "=" in line else ""
820	        if key_match in remove_set:
821	            continue
822	        if key_match in env_writes:
823	            updated_keys.add(key_match)
824	        new_lines.append(f"{key_match}={_env_line_safe(env_writes[key_match])}" if key_match in env_writes else line)
825	    new_lines += [f"{key}={_env_line_safe(val)}" for key, val in env_writes.items() if key not in updated_keys]
826	    _secure_secret_file(env_path, create=True)
827	    env_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8", errors="surrogateescape")
828	    _secure_secret_file(env_path)
829
830
831	def _ovcli_data_from_connection_values(values: dict) -> dict:
832	    data = {"url": _normalize_openviking_url(_clean_config_value(values.get("endpoint")) or _DEFAULT_ENDPOINT)}
833	    for out_key, in_key in (("api_key", "api_key"), ("root_api_key", "root_api_key"), ("account", "account"), ("user", "user"), ("actor_peer_id", "agent")):
```


> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
