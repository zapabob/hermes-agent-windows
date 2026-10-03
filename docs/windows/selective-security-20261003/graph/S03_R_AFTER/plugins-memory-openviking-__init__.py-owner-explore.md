**Exploration: plugins/memory/openviking/__init__.py**

Found 254 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/memory/openviking/__init__.py`** — calls(calls), get(calls), _clean_config_value(calls), post(calls), _token_units(calls), _ensure_client(calls), _unwrap_result(calls), _normalize_openviking_url(calls), _emit_runtime(calls), _message_text(calls), _status_code_from_error(calls), _format_openviking_exception(calls), _load_hermes_openviking_config(calls), _settings_tuple(calls), _remaining_recall_timeout(calls), +389 more

```python
158
159
160	def _sanitize_openviking_error_message(message: str, status_code: Optional[int] = None) -> str:
161	    text = (message or "").strip()
162	    status = f"HTTP {status_code}" if status_code else "HTTP error"
163	    if re.search(r"^\s*<(!doctype|html|head|body)\b", text, flags=re.IGNORECASE):
164	        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
165	        if title_match:
166	            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
167	            title = title.split("|", 1)[1].strip() if "|" in title else title
168	            title = title.split(":", 1)[1].strip() if status_code and title.startswith(f"{status_code}:") else title
169	            if title:
170	                return f"{status}: {title}"
171	        return f"{status}: OpenViking endpoint returned an HTML error page."
172	    if len(text) > 300:
173	        return text[:297].rstrip() + "..."
174	    return text or status
175
176
177	def _status_code_from_error(error: Exception) -> Optional[int]:
178	    if isinstance(error, _OpenVikingHTTPError):
179	        return error.status_code
180	    return getattr(getattr(error, "response", None), "status_code", None)
181
182
183	def _format_openviking_exception(error: Exception) -> str:
184	    return _sanitize_openviking_error_message(str(error), _status_code_from_error(error))
185
186
187	def _derive_openviking_user_text(content: Any) -> str:
188	    """Strip Hermes slash-skill scaffolding before sending content to OpenViking
189	    (MemoryManager already does this for the fan-out; kept for direct hook callers)."""
190	    return extract_user_instruction_from_skill_message(content) or ""
191
192
193	def _preview(value: Any, limit: int = 160) -> str:
194	    text = ("" if value is None else str(value)).replace("\n", "\\n")
195	    return text[:limit] + "..." if len(text) > limit else text
196
197

... (gap) ...

208	    _last_active_provider = None
209	    try:
210	        with suppress(Exception):  # best-effort at shutdown time
211	            provider.on_session_end([])
212	    finally:
213	        # ``finally`` (as on main): the run lock is released even when on_session_end
214	        # dies of a BaseException (KeyboardInterrupt during atexit).
215	        with suppress(Exception):
216	            provider._release_run_lock()
217
218
219	atexit.register(_atexit_commit_sessions)

... (gap) ...

237	        self._api_key = api_key
238	        # Account/user are local/trusted-mode tenant identity. API-key requests
239	        # omit these headers unless OpenViking explicitly asks for them (retry).
240	        self._account = account or os.environ.get("OPENVIKING_ACCOUNT", "default")
241	        self._user = user or os.environ.get("OPENVIKING_USER", "default")
242	        self._agent = agent if agent is not None else os.environ.get("OPENVIKING_AGENT", _DEFAULT_AGENT)
243	        self._httpx = _get_httpx()
244	        if self._httpx is None:
245	            raise ImportError("httpx is required for OpenViking: pip install httpx")
246

... (gap) ...

268	        return getattr(exc, "status_code", None) in (None, 400)
269
270	    def _multipart_headers(self, *, include_tenant: bool | None = None) -> dict:
271	        headers = self._headers(include_tenant=include_tenant)
272	        headers.pop("Content-Type", None)
273	        return headers
274
275	    def _send_with_trusted_identity_retry(self, send, *, multipart: bool = False) -> dict:
276	        build = self._multipart_headers if multipart else self._headers
277	        try:
278	            return self._parse_response(send(build()))
279	        except Exception as exc:
280	            if not self._api_key or not self._needs_trusted_identity_retry(exc):
281	                raise
282	            return self._parse_response(send(build(include_tenant=True)))
283
284	    def _parse_response(self, resp) -> dict:
285	        data = None
286	        with suppress(Exception):
287	            data = resp.json()
288	        error = data.get("error") if isinstance(data, dict) else None
289	        if resp.status_code >= 400:
290	            message = _sanitize_openviking_error_message(getattr(resp, "text", ""), resp.status_code)
291	            if isinstance(error, dict):
292	                raise _OpenVikingHTTPError(f"{error.get('code', 'HTTP_ERROR')}: {error.get('message', message)}", resp.status_code)
293	            if isinstance(data, dict) and data.get("status") == "error":
294	                raise _OpenVikingHTTPError(str(data), resp.status_code)
295	            raise _OpenVikingHTTPError(message or f"HTTP {resp.status_code}", resp.status_code)
296	        if isinstance(data, dict) and data.get("status") == "error":
297	            if isinstance(error, dict):
298	                raise RuntimeError(f"{error.get('code', 'OPENVIKING_ERROR')}: {error.get('message', '')}")
299	            raise RuntimeError(str(data))
300	        return {} if data is None else data
301
302	    def _request(self, method: str, path: str, kwargs: dict) -> dict:
303	        timeout = kwargs.pop("timeout", _TIMEOUT)
304	        fn = getattr(self._httpx, method)
305	        return self._send_with_trusted_identity_retry(lambda headers: fn(f"{self._endpoint}{path}", headers=headers, timeout=timeout, **kwargs))
306
307	    def get(self, path: str, **kwargs) -> dict:
308	        return self._request("get", path, kwargs)
309
310	    def post(self, path: str, payload: dict = None, **kwargs) -> dict:
311	        return self._request("post", path, {**kwargs, "json": payload or {}})
312
313	    def delete(self, path: str, **kwargs) -> dict:
314	        return self._request("delete", path, kwargs)
315
316	    def upload_temp_file(self, file_path: Path) -> str:
317	        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
318
319	        def _send(headers):
320	            with file_path.open("rb") as f:
321	                return self._httpx.post(f"{self._endpoint}/api/v1/resources/temp_upload",
322	                                        files={"file": (file_path.name, f, mime_type)}, headers=headers, timeout=_TIMEOUT)
323
324	        temp_file_id = self._send_with_trusted_identity_retry(_send, multipart=True).get("result", {}).get("temp_file_id", "")
325	        if not temp_file_id:
326	            raise RuntimeError("OpenViking temp upload did not return temp_file_id")
327	        return temp_file_id
328
329	    def health(self) -> bool:
330	        with suppress(Exception):
331	            return _probe_openviking_identity(self)[0] in _OPENVIKING_IDENTIFIED_STATES
332	        return False
333
334	    def _anonymous_json(self, path: str) -> dict:
335	        """Probe server identity without disclosing credentials or tenant IDs."""
336	        return self._parse_response(self._httpx.get(f"{self._endpoint}{path}", headers={"Accept": "application/json"}, timeout=3.0))
337
338	    def health_payload(self) -> dict:
339	        """``GET /health``, anonymous first so credentials never reach an unknown host.
340	        Hosted OpenViking requires auth on /health: when an API key is configured and the
341	        anonymous call gets 401/403, retry once with the key (no tenant headers).
342
343	        Prefer an anonymous probe so credentials are never sent to an unknown host during identity checks.
344	        See #78410.
345	        """
346	        try:
347	            return self._anonymous_json("/health")
348	        except _OpenVikingHTTPError as exc:
349	            if not self._api_key or _status_code_from_error(exc) not in {401, 403}:
350	                raise
351	            return self._parse_response(self._httpx.get(f"{self._endpoint}/health", headers=self._headers(include_tenant=False), timeout=3.0))
352
353	    def openapi_payload(self) -> dict:
354	        return self._anonymous_json("/openapi.json")
355
356	    def validate_auth(self) -> dict:  # authenticated access, no mutation
357	        return self.get("/api/v1/system/status")
358
359	    def validate_root_access(self) -> dict:  # ROOT access via a read-only admin endpoint
360	        return self.get("/api/v1/admin/accounts")
361
362
363	# -- Tool schemas -----------------------------------------------------------

... (gap) ...

459	    reports no user. Callers may fall back to a configured value for that one operation but
460	    must not cache an unverified identity — a later probe can succeed."""
461	    try:
462	        status = client.get("/api/v1/system/status", **({"timeout": timeout} if timeout is not None else {}))
463	    except Exception:
464	        logger.debug("OpenViking user-space probe failed; using configured fallback", exc_info=True)
465	        return None
466	    return str(((status or {}).get("result") or {}).get("user") or "").strip() or None
467
468
469	def _zip_directory(dir_path: Path) -> Path:

... (gap) ...

479	            try:
480	                resolved = file_path.resolve()
481	                resolved.relative_to(root)
482	                raise_if_read_blocked(str(resolved))
483	            except ValueError:
484	                continue
485	            zipf.write(file_path, arcname=str(file_path.relative_to(dir_path)).replace("\\", "/"))
486	    return zip_path
487
488

... (gap) ...

501	        return None, "viking_forget requires an exact URI without query or fragment"
502	    if uri.endswith("/") or not uri.endswith(".md"):
503	        return None, "viking_forget only deletes concrete .md memory files"
504	    parts = [part for part in uri[len("viking://") :].split("/") if part]
505	    # ``memories`` segment index for the user / user-uid / peer / uid-peer layouts.
506	    memories_idx = next((idx for idx, peer_at in ((1, None), (2, None), (3, 1), (4, 2))
507	                         if parts[:1] == ["user"] and len(parts) > idx and parts[idx] == "memories" and (peer_at is None or parts[peer_at] == "peers")), None)
508	    if memories_idx is None or len(parts) < memories_idx + 2:
509	        return None, "viking_forget only deletes user memory file URIs"
510	    if uri.rsplit("/", 1)[-1] in _GENERATED_MEMORY_SUMMARY_FILENAMES:
511	        return None, "viking_forget cannot delete generated memory summary files"
512	    return uri, None
513
514
515	def _is_local_path_reference(value: str) -> bool:
516	    if not value or "\n" in value or "\r" in value or value.startswith(_REMOTE_RESOURCE_PREFIXES):
517	        return False
518	    if _is_windows_absolute_path(value):
519	        return True
520	    return value.startswith(("/", "./", "../", "~/", ".\\", "..\\", "~\\")) or "/" in value or "\\" in value
521
522
523	def _clean_config_value(value: Any) -> str:
524	    return value.strip() if isinstance(value, str) else ""
525
526
527	def _openviking_endpoint_label(value: Any) -> str:
528	    """Credential-free endpoint label for logs and UI."""
529	    raw = _clean_config_value(value)
530	    if not raw:
531	        return "<empty endpoint>"
532	    try:

... (gap) ...

544
545
546	def _default_ovcli_config_path() -> Path:
547	    return Path.home() / _OVCLI_DEFAULT_RELATIVE_PATH
548
549
550	def _resolve_ovcli_config_path(config_path: str = "") -> Path:
551	    chosen = os.environ.get(_OVCLI_CONFIG_ENV, "").strip() or config_path
552	    return Path(chosen).expanduser() if chosen else _default_ovcli_config_path()
553
554
555	def _load_ovcli_config(path: Optional[Path] = None) -> dict:
556	    config_path = path or _resolve_ovcli_config_path()
557	    if not config_path.exists():
558	        return {}
559	    data = json.loads(config_path.read_text(encoding="utf-8"))
560	    if not isinstance(data, dict):
561	        raise ValueError(f"OpenViking CLI config must be a JSON object: {config_path}")
562	    return data
563
564
565	def _connection_values_from_ovcli(data: dict) -> dict:
566	    endpoint_value = _clean_config_value(data.get("url"))
567	    api_key = _clean_config_value(data.get("api_key")) or _clean_config_value(data.get("root_api_key"))
568	    root_api_key = _clean_config_value(data.get("root_api_key"))
569	    send_identity = not api_key or api_key == root_api_key  # user keys derive tenant server-side
570	    return {
571	        # No URL -> no endpoint; the resolver continues to config.yaml, then the default.
572	        "endpoint": _normalize_openviking_url(endpoint_value) if endpoint_value else "",
573	        "api_key": api_key,
574	        "root_api_key": root_api_key,
575	        "account": _clean_config_value(data.get("account") or data.get("account_id")) if send_identity else "",
576	        "user": _clean_config_value(data.get("user") or data.get("user_id")) if send_identity else "",
577	        "agent": _clean_config_value(data.get("actor_peer_id") or data.get("agent_id")),
578	    }
579
580

... (gap) ...

607	    on every access (Dashboard / ``/reload``), so slow DNS lookups stay off the hot path."""
608	    from tools.url_safety import is_always_blocked_url
609
610	    return is_always_blocked_url(candidate)
611
612
613	def _normalize_openviking_url(url: str) -> str:
614	    trimmed = _clean_config_value(url).rstrip("/")
615	    if not trimmed:
616	        return _DEFAULT_ENDPOINT
617	    lower = trimmed.lower()

... (gap) ...

631	        if parsed.username or parsed.password or parsed.query or parsed.fragment:
632	            raise ValueError("OpenViking endpoints cannot contain user info, query parameters, or fragments.")
633	    except ValueError as exc:
634	        raise _OpenVikingEndpointError(f"Invalid OpenViking endpoint {_openviking_endpoint_label(candidate)}: {exc}") from exc
635
636	    # Local/LAN self-host stays allowed; reject cloud-metadata floors so a poisoned
637	    # endpoint cannot SSRF via memory sync. Never silently substitute localhost for
638	    # an unsafe endpoint — that could forward credentials to the wrong deployment.
639	    try:
640	        blocked = _openviking_endpoint_is_always_blocked(candidate)
641	    except Exception as exc:
642	        logger.debug("OpenViking endpoint safety validation failed", exc_info=True)
643	        raise _OpenVikingEndpointError("OpenViking endpoint safety validation failed; Hermes refused the connection.") from exc
644	    if blocked:
645	        raise _OpenVikingEndpointError(
646	            f"OpenViking endpoint {_openviking_endpoint_label(candidate)} targets a blocked metadata address."
647	        )
648	    return candidate
649
650
651	def _probe_openviking_identity(client: _VikingClient) -> tuple[str, Any]:
652	    """Identify modern or legacy OpenViking before any authenticated request.
653	    -> ("modern" | "legacy" | "legacy-unverified" | "unhealthy" | "invalid", health).
654	    Modern = documented status/healthy/version contract; legacy = status-only (<= 0.2.6),
655	    which must be confirmed via the anonymous OpenAPI title."""
656	    health = client.health_payload()
657	    if isinstance(health, dict) and health.get("healthy") is False:
658	        return "unhealthy", health
659	    if not isinstance(health, dict) or health.get("status") != "ok":
660	        return "invalid", health
661	    if health.get("healthy") is True and isinstance(health.get("version"), str) and health["version"].strip():
662	        return "modern", health
663	    if "healthy" in health or "version" in health:
664	        return "invalid", health
665	    try:
666	        info = client.openapi_payload().get("info")
667	        verified = isinstance(info, dict) and info.get("title") == "OpenViking API"
668	    except Exception:
669	        logger.debug("Legacy OpenViking OpenAPI identity probe failed", exc_info=True)
670	        verified = False
671	    return ("legacy" if verified else "legacy-unverified"), health
672
673
674	def _load_profile(path: Path, *, source: str, name: str) -> Optional[_OvcliProfile]:
675	    try:
676	        values = _connection_values_from_ovcli(_load_ovcli_config(path))
677	    except Exception as e:
678	        logger.warning("Skipping invalid OpenViking CLI config %s: %s", path, _format_openviking_exception(e))
679	        return None
680	    return _OvcliProfile(source=source, name=name, path=path, values=values)
681
682
683	def _profile_identity(path: Path) -> str:
684	    try:
685	        return str(path.expanduser().resolve())
686	    except OSError:
687	        return str(path.expanduser())
688
689
690	def _discover_ovcli_profiles() -> list[_OvcliProfile]:
691	    """env-pointed config, then saved ``ovcli.conf.<name>`` files, then the active
692	    ``ovcli.conf`` — which is only listed on its own when no saved profile has
693	    identical connection values and nothing else was found."""
694	    profiles: list[_OvcliProfile] = []
695	    seen_paths: set[str] = set()
696
697	    def add(path: Path, *, source: str, name: str) -> None:
698	        identity = _profile_identity(path)
699	        if path.is_file() and identity not in seen_paths and (profile := _load_profile(path, source=source, name=name)) is not None:
700	            seen_paths.add(identity)
701	            profiles.append(profile)
702
703	    env_path = os.environ.get(_OVCLI_CONFIG_ENV, "").strip()
704	    if env_path:
705	        add(Path(env_path).expanduser(), source="env", name=_OVCLI_CONFIG_ENV)
706
707	    active_path = _default_ovcli_config_path()
708	    active_profile = _load_profile(active_path, source="active", name="active") if active_path.exists() else None
709
710	    config_dir = _default_ovcli_config_path().parent
711	    saved_start = len(profiles)
712	    if config_dir.exists():
713	        for path in sorted(config_dir.iterdir(), key=lambda item: item.name):
714	            name = path.name.removeprefix(_OVCLI_SAVED_PREFIX)
715	            if path.is_file() and name != path.name and name != "bak" and _is_valid_ovcli_profile_name(name):
716	                add(path, source="saved", name=name)
717
718	    if active_profile is not None:
719	        marked_active = False
720	        for idx in range(saved_start, len(profiles)):
721	            if profiles[idx].source == "saved" and profiles[idx].values == active_profile.values:
722	                profiles[idx] = replace(profiles[idx], is_active=True)
723	                marked_active = True
724	                break
725	        if not marked_active and not profiles and _profile_identity(active_profile.path) not in seen_paths:
726	            profiles.append(active_profile)
727	    return profiles
728
729
730	def _is_local_openviking_url(value: str) -> bool:
731	    try:
732	        candidate = _normalize_openviking_url(value)
733	    except _OpenVikingEndpointError:
734	        return False
735	    parsed = urlparse(candidate)
736	    return parsed.scheme.lower() == "http" and (parsed.hostname or "").lower() in _LOCAL_OPENVIKING_HOSTS
737
738
739	def _load_hermes_openviking_config() -> dict:
740	    try:
741	        from hermes_cli.config import load_config_readonly
742
743	        config = load_config_readonly()
744	        memory_config = config.get("memory", {}) if isinstance(config, dict) else {}
745	        provider_config = memory_config.get("openviking", {}) if isinstance(memory_config, dict) else {}
746	        return dict(provider_config) if isinstance(provider_config, dict) else {}
747	    except Exception:
748	        return {}
749
750
751	def _ovcli_values_for(provider_config: dict) -> dict:
752	    """Connection values from the linked ovcli profile, or {} when none is linked."""
753	    if not provider_config.get("use_ovcli_config"):
754	        return {}
755	    ovcli_path = _resolve_ovcli_config_path(str(provider_config.get("ovcli_config_path") or ""))
756	    return _connection_values_from_ovcli(_load_ovcli_config(ovcli_path))
757
758
759	def _resolve_connection_settings(provider_config: Optional[dict] = None) -> dict:
760	    """Layering: env -> linked ovcli profile -> config.yaml -> built-in default.
761	    An env account/user (even empty) is authoritative; the secret api_key never
762	    comes from config.yaml."""
763	    provider_config = dict(provider_config or {})
764	    ovcli_values = _ovcli_values_for(provider_config)
765
766	    def layered(key: str, default: str = "", *, env_authoritative: bool = False) -> str:
767	        env = os.environ.get(f"OPENVIKING_{key.upper()}")
768	        if env is not None:
769	            env = env.strip()
770	            if env_authoritative:
771	                return env
772	        return env or ovcli_values.get(key) or _clean_config_value(provider_config.get(key)) or default
773
774	    api_key_env = os.environ.get("OPENVIKING_API_KEY")
775	    return {
776	        "endpoint": _normalize_openviking_url(layered("endpoint", _DEFAULT_ENDPOINT)),
777	        "api_key": api_key_env.strip() if api_key_env is not None else ovcli_values.get("api_key", ""),
778	        "account": layered("account", env_authoritative=True),
779	        "user": layered("user", env_authoritative=True),
780	        "agent": layered("agent", _DEFAULT_AGENT),
781	    }
782
783
784	def _secure_secret_file(path: Path, *, create: bool = False) -> None:
785	    """chmod 0600 a secret-bearing file; with ``create`` also pre-create it BEFORE writing
786	    (write-then-chmod leaves a window where the fresh file is world-readable under the umask)."""
787	    try:
788	        if create and not path.exists():
789	            os.close(os.open(str(path), os.O_CREAT | os.O_WRONLY, 0o600))
790	        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
791	    except OSError as e:
792	        logger.debug("Could not %s secret file %s: %s", "pre-create" if create else "restrict permissions on", path, e)
793
794
795	def _env_line_safe(value: Any) -> str:
796	    """Strip CR/LF/NUL so a value can only occupy its single ``KEY=VALUE`` line — an
797	    embedded line break would be re-parsed as a separate variable (secret injection)."""
798	    text = value if isinstance(value, str) else str(value)
799	    return "".join(text.replace("\x00", "").splitlines())
800
801
802	def _write_env_vars(env_path: Path, env_writes: dict, remove_keys: tuple[str, ...] = ()) -> None:
803	    env_path.parent.mkdir(parents=True, exist_ok=True)
804	    remove_set = set(remove_keys) - set(env_writes)
805	    # utf-8-sig + surrogateescape: a Windows editor may leave a BOM (breaks the
806	    # first key match) or save cp1252; round-trip undecodable bytes unchanged so
807	    # updating one credential cannot corrupt an unrelated value.
808	    existing_lines = env_path.read_text(encoding="utf-8-sig", errors="surrogateescape").splitlines() if env_path.exists() else []
809	    updated_keys = set()
810	    new_lines = []
811	    for line in existing_lines:
812	        key_match = line.split("=", 1)[0].strip() if "=" in line else ""
813	        if key_match in remove_set:
814	            continue
815	        if key_match in env_writes:
816	            updated_keys.add(key_match)
817	        new_lines.append(f"{key_match}={_env_line_safe(env_writes[key_match])}" if key_match in env_writes else line)
818	    new_lines += [f"{key}={_env_line_safe(val)}" for key, val in env_writes.items() if key not in updated_keys]
819	    _secure_secret_file(env_path, create=True)
820	    env_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8", errors="surrogateescape")
821	    _secure_secret_file(env_path)
822
823
824	def _ovcli_data_from_connection_values(values: dict) -> dict:
825	    data = {"url": _normalize_openviking_url(_clean_config_value(values.get("endpoint")) or _DEFAULT_ENDPOINT)}
826	    for out_key, in_key in (("api_key", "api_key"), ("root_api_key", "root_api_key"), ("account", "account"), ("user", "user"), ("actor_peer_id", "agent")):
827	        value = _clean_config_value(values.get(in_key))
828	        if value:
```
