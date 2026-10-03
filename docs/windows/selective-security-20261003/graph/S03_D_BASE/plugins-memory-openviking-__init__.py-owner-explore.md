**Exploration: plugins/memory/openviking/__init__.py**

Found 300 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/memory/openviking/__init__.py`** — calls(calls), _clean_config_value(calls), get(calls), _token_units(calls), post(calls), _normalize_openviking_url(calls), _VikingClient(instantiates), _retry_or_cancel_manual_setup(calls), _ensure_client(calls), _format_openviking_exception(calls), _unwrap_result(calls), _message_text(calls), _user_scoped_uri(calls), _url(calls), _env_value(calls), +484 more

```python
117	    """
118	    try:
119	        kwargs = {"timeout": timeout} if timeout is not None else {}
120	        status = client.get("/api/v1/system/status", **kwargs)
121	        result = (status or {}).get("result") or {}
122	        user = str(result.get("user") or "").strip()
123	        if user:
124	            return user
125	    except Exception:

... (gap) ...

224
225
226	def _sanitize_openviking_error_message(message: str, status_code: Optional[int] = None) -> str:
227	    text = (message or "").strip()
228	    status = f"HTTP {status_code}" if status_code else "HTTP error"
229	    looks_like_html = bool(re.search(r"^\s*<(!doctype|html|head|body)\b", text, flags=re.IGNORECASE))
230	    if looks_like_html:
231	        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
232	        if title_match:
233	            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
234	            if "|" in title:
235	                title = title.split("|", 1)[1].strip()
236	            if status_code and title.startswith(f"{status_code}:"):
237	                title = title.split(":", 1)[1].strip()
238	            if title:
239	                return f"{status}: {title}"
240	        return f"{status}: OpenViking endpoint returned an HTML error page."
241
242	    if len(text) > 300:
243	        return text[:297].rstrip() + "..."
244	    return text or status
245
246
247	def _format_openviking_exception(error: Exception) -> str:
248	    status_code = None
249	    if isinstance(error, _OpenVikingHTTPError):
250	        status_code = error.status_code
251	    else:
252	        response = getattr(error, "response", None)
253	        status_code = getattr(response, "status_code", None)
254	    return _sanitize_openviking_error_message(str(error), status_code)
255
256
257	def _derive_openviking_user_text(content: Any) -> str:
258	    """Strip Hermes slash-skill scaffolding before sending content to OpenViking.
259
260	    Defense-in-depth: MemoryManager already strips skill scaffolding for the
261	    whole provider fan-out (see ``MemoryManager._strip_skill_scaffolding``), so
262	    in normal operation this receives already-clean text and passes it through
263	    unchanged. It stays here so OpenViking is correct if its hooks are ever
264	    invoked outside the manager. Delegates to the canonical extractor in
265	    ``agent.skill_commands`` — no duplicated marker literals, no drift risk.
266	    """
267	    return extract_user_instruction_from_skill_message(content) or ""
268
269
270	def _sync_trace_enabled() -> bool:
271	    return env_var_enabled(_SYNC_TRACE_ENV)
272
273
274	def _preview(value: Any, limit: int = 160) -> str:
275	    text = "" if value is None else str(value)
276	    text = text.replace("\n", "\\n")
277	    if len(text) > limit:
278	        return text[:limit] + "..."
279	    return text

... (gap) ...

295	        return
296	    _last_active_provider = None
297	    try:
298	        provider.on_session_end([])
299	    except Exception:
300	        pass  # best-effort at shutdown time
301	    finally:
302	        try:
303	            provider._release_run_lock()
304	        except Exception:
305	            pass
306

... (gap) ...

334	        # after OpenViking explicitly asks for asserted tenant identity.
335	        # Tenant identity is a profile .env value: scope-read so a multiplexed
336	        # secondary never writes into the default profile's tenant.
337	        self._account = account or get_secret("OPENVIKING_ACCOUNT", "") or "default"
338	        self._user = user or get_secret("OPENVIKING_USER", "") or "default"
339	        self._agent = agent if agent is not None else (
340	            get_secret("OPENVIKING_AGENT", "") or _DEFAULT_AGENT
341	        )
342	        self._httpx = _get_httpx()
343	        if self._httpx is None:
344	            raise ImportError("httpx is required for OpenViking: pip install httpx")
345

... (gap) ...

367	        return f"{self._endpoint}{path}"
368
369	    def _multipart_headers(self, *, include_tenant: bool | None = None) -> dict:
370	        headers = self._headers(include_tenant=include_tenant)
371	        headers.pop("Content-Type", None)
372	        return headers
373

... (gap) ...

393
394	    def _send_with_trusted_identity_retry(self, send, *, multipart: bool = False) -> dict:
395	        try:
396	            headers = self._multipart_headers() if multipart else self._headers()
397	            return self._parse_response(send(headers))
398	        except Exception as exc:
399	            if not self._api_key or not self._needs_trusted_identity_retry(exc):
400	                raise
401	            headers = (
402	                self._multipart_headers(include_tenant=True)
403	                if multipart else self._headers(include_tenant=True)
404	            )
405	            return self._parse_response(send(headers))
406
407	    def _parse_response(self, resp) -> dict:
408	        try:
409	            data = resp.json()
410	        except Exception:
411	            data = None
412
413	        if resp.status_code >= 400:
414	            message = _sanitize_openviking_error_message(
415	                getattr(resp, "text", ""),
416	                resp.status_code,
417	            )
418	            if isinstance(data, dict):
419	                error = data.get("error")
420	                if isinstance(error, dict):
421	                    code = error.get("code", "HTTP_ERROR")
422	                    message = f"{code}: {error.get('message', message)}"
423	                    raise _OpenVikingHTTPError(message, resp.status_code)
424	                if data.get("status") == "error":
425	                    raise _OpenVikingHTTPError(str(data), resp.status_code)
426	            raise _OpenVikingHTTPError(message or f"HTTP {resp.status_code}", resp.status_code)
427
428	        if isinstance(data, dict) and data.get("status") == "error":
429	            error = data.get("error")

... (gap) ...

439
440	    def get(self, path: str, **kwargs) -> dict:
441	        timeout = kwargs.pop("timeout", _TIMEOUT)
442	        return self._send_with_trusted_identity_retry(
443	            lambda headers: self._httpx.get(
444	                self._url(path), headers=headers, timeout=timeout, **kwargs
445	            )
446	        )
447
448	    def post(self, path: str, payload: dict = None, **kwargs) -> dict:
449	        timeout = kwargs.pop("timeout", _TIMEOUT)
450	        return self._send_with_trusted_identity_retry(
451	            lambda headers: self._httpx.post(
452	                self._url(path), json=payload or {}, headers=headers,
453	                timeout=timeout, **kwargs
454	            )
455	        )
456
457	    def delete(self, path: str, **kwargs) -> dict:
458	        timeout = kwargs.pop("timeout", _TIMEOUT)
459	        return self._send_with_trusted_identity_retry(
460	            lambda headers: self._httpx.delete(
461	                self._url(path), headers=headers, timeout=timeout, **kwargs
462	            )
463	        )
464
465	    def upload_temp_file(self, file_path: Path) -> str:
466	        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
467
468	        def _send(headers):
469	            with file_path.open("rb") as f:
470	                return self._httpx.post(
471	                    self._url("/api/v1/resources/temp_upload"),
472	                    files={"file": (file_path.name, f, mime_type)},
473	                    headers=headers,
474	                    timeout=_TIMEOUT,
475	                )
476
477	        data = self._send_with_trusted_identity_retry(_send, multipart=True)
478	        result = data.get("result", {})
479	        temp_file_id = result.get("temp_file_id", "")
480	        if not temp_file_id:
481	            raise RuntimeError("OpenViking temp upload did not return temp_file_id")
482	        return temp_file_id
483
484	    def health(self) -> bool:
485	        try:
486	            identity, _health = _probe_openviking_identity(self)
487	            return identity in _OPENVIKING_IDENTIFIED_STATES
488	        except Exception:
489	            return False
490
491	    def _anonymous_json(self, path: str) -> dict:
492	        """Probe server identity without disclosing credentials or tenant IDs."""
493	        resp = self._httpx.get(
494	            self._url(path),
495	            headers={"Accept": "application/json"},
496	            timeout=3.0,
497	        )
498	        return self._parse_response(resp)
499
500	    def _authenticated_json(self, path: str) -> dict:
501	        """JSON GET with the configured API key (no tenant headers).
502
503	        Used only after an anonymous probe is rejected for missing auth, so we
504	        still avoid disclosing credentials to a server that answers health
505	        anonymously.
506	        """
507	        headers = self._headers(include_tenant=False)
508	        resp = self._httpx.get(
509	            self._url(path), headers=headers, timeout=3.0
510	        )
511	        return self._parse_response(resp)
512
513	    @staticmethod
514	    def _health_requires_credentials(exc: Exception) -> bool:
515	        """True when /health rejected the anonymous probe for auth reasons."""
516	        return _status_code_from_error(exc) in {401, 403}
517
518	    def health_payload(self) -> dict:
519	        """Fetch ``GET /health``.
520
521	        Prefer an anonymous probe so credentials are never sent to an unknown
522	        host during identity checks. Hosted OpenViking (e.g. Volcengine cloud)
523	        requires authentication on ``/health``; when an API key is configured
524	        and the anonymous call is rejected for auth, retry once with that key
525	        so automatic memory mirroring is not silently disabled (#78410).
526	        """
527	        try:
528	            return self._anonymous_json("/health")
529	        except _OpenVikingHTTPError as exc:
530	            if not self._api_key or not self._health_requires_credentials(exc):
531	                raise
532	            return self._authenticated_json("/health")
533
534	    def openapi_payload(self) -> dict:
535	        return self._anonymous_json("/openapi.json")
536
537	    def validate_auth(self) -> dict:
538	        """Validate authenticated OpenViking access without mutating state."""
539	        return self.get("/api/v1/system/status")
540
541	    def validate_root_access(self) -> dict:
542	        """Validate ROOT access against a read-only admin endpoint."""
543	        return self.get("/api/v1/admin/accounts")
544
545
546	# ---------------------------------------------------------------------------

... (gap) ...

745	                except ValueError:
746	                    continue
747	                try:
748	                    raise_if_read_blocked(str(resolved))
749	                except ValueError:
750	                    continue
751	                arcname = str(file_path.relative_to(dir_path)).replace("\\", "/")
752	                zipf.write(file_path, arcname=arcname)
753	    return zip_path
754

... (gap) ...

794	    if uri.endswith("/") or not uri.endswith(".md"):
795	        return None, "viking_forget only deletes concrete .md memory files"
796
797	    parts = [part for part in uri[len("viking://") :].split("/") if part]
798	    memories_idx = _memory_segment_index(parts)
799	    if memories_idx is None or len(parts) < memories_idx + 2:
800	        return None, "viking_forget only deletes user memory file URIs"
801
802	    filename = uri.rsplit("/", 1)[-1]
803	    if filename in _GENERATED_MEMORY_SUMMARY_FILENAMES:
804	        return None, "viking_forget cannot delete generated memory summary files"
805
806	    return uri, None
807
808
809	def _is_local_path_reference(value: str) -> bool:
810	    if not value or "\n" in value or "\r" in value:
811	        return False
812	    if _is_remote_resource_source(value):
813	        return False
814	    if _is_windows_absolute_path(value):
815	        return True
816	    return (
817	        value.startswith(("/", "./", "../", "~/", ".\\", "..\\", "~\\"))

... (gap) ...

833
834	def _openviking_endpoint_label(value: Any) -> str:
835	    """Return a credential-free endpoint label suitable for logs and UI."""
836	    raw = _clean_config_value(value)
837	    if not raw:
838	        return "<empty endpoint>"
839	    try:

... (gap) ...

853
854
855	def _default_ovcli_config_path() -> Path:
856	    return Path.home() / _OVCLI_DEFAULT_RELATIVE_PATH
857
858
859	def _resolve_ovcli_config_path(config_path: str = "") -> Path:
860	    env_path = os.environ.get(_OVCLI_CONFIG_ENV, "").strip()
861	    if env_path:
862	        return Path(env_path).expanduser()
863	    if config_path:
864	        return Path(config_path).expanduser()
865	    return _default_ovcli_config_path()
866
867
868	def _ovcli_config_dir() -> Path:
869	    return _default_ovcli_config_path().parent
870
871
872	def _load_ovcli_config(path: Optional[Path] = None) -> dict:
873	    config_path = path or _resolve_ovcli_config_path()
874	    if not config_path.exists():
875	        return {}
876	    with config_path.open(encoding="utf-8") as f:
877	        data = json.load(f)
878	    if not isinstance(data, dict):
879	        raise ValueError(f"OpenViking CLI config must be a JSON object: {config_path}")
880	    return data
881
882
883	def _connection_values_from_ovcli(data: dict) -> dict:
884	    endpoint_value = _clean_config_value(data.get("url"))
885	    api_key = _clean_config_value(data.get("api_key")) or _clean_config_value(data.get("root_api_key"))
886	    root_api_key = _clean_config_value(data.get("root_api_key"))
887	    send_identity = not api_key or api_key == root_api_key
888	    account = _clean_config_value(data.get("account") or data.get("account_id"))
889	    user = _clean_config_value(data.get("user") or data.get("user_id"))
890	    return {
891	        # A linked profile with no URL contributes no endpoint; the resolver
892	        # can then continue to config.yaml and finally the built-in default.
893	        "endpoint": _normalize_openviking_url(endpoint_value) if endpoint_value else "",
894	        "api_key": api_key,
895	        "root_api_key": root_api_key,
896	        "account": account if send_identity else "",
897	        "user": user if send_identity else "",
898	        "agent": _clean_config_value(data.get("actor_peer_id") or data.get("agent_id")),
899	    }
900
901

... (gap) ...

936	    """
937	    from tools.url_safety import is_always_blocked_url
938
939	    return is_always_blocked_url(candidate)
940
941
942	def _normalize_openviking_url(url: str) -> str:
943	    trimmed = _clean_config_value(url).rstrip("/")
944	    if not trimmed:
945	        return _DEFAULT_ENDPOINT
946	    lower = trimmed.lower()

... (gap) ...

966	                "OpenViking endpoints cannot contain user info, query parameters, or fragments."
967	            )
968	    except ValueError as exc:
969	        raise _OpenVikingEndpointError(
970	            f"Invalid OpenViking endpoint {_openviking_endpoint_label(candidate)}: {exc}"
971	        ) from exc
972
973	    # Local / LAN self-host remains allowed; reject cloud-metadata and other
974	    # always-blocked floors so a poisoned endpoint cannot SSRF via memory sync.
975	    # Never silently replace an explicitly unsafe endpoint with localhost: that
976	    # could attach Hermes to an unrelated deployment and forward credentials to
977	    # a destination the user did not configure.
978	    try:
979	        check_url = candidate
980	        if _openviking_endpoint_is_always_blocked(check_url):
981	            raise _OpenVikingEndpointError(
982	                "OpenViking endpoint "
983	                f"{_openviking_endpoint_label(candidate)} targets a blocked metadata address."
984	            )
985	    except _OpenVikingEndpointError:
986	        raise
987	    except Exception as exc:
988	        logger.debug("OpenViking endpoint safety validation failed", exc_info=True)
989	        raise _OpenVikingEndpointError(
990	            "OpenViking endpoint safety validation failed; Hermes refused the connection."
991	        ) from exc
992
993	    return candidate
994
995
996	def _is_openviking_health_payload(payload: Any) -> bool:
997	    """Match OpenViking's documented ``GET /health`` response contract."""
998	    return (
999	        isinstance(payload, dict)
1000	        and payload.get("status") == "ok"
1001	        and payload.get("healthy") is True
1002	        and isinstance(payload.get("version"), str)
1003	        and bool(payload["version"].strip())
1004	    )
1005
1006

... (gap) ...

1023
1024	def _probe_openviking_identity(client: _VikingClient) -> tuple[str, Any]:
1025	    """Identify modern or legacy OpenViking before any authenticated request."""
1026	    health = client.health_payload()
1027	    if isinstance(health, dict) and health.get("healthy") is False:
1028	        return _OPENVIKING_IDENTITY_UNHEALTHY, health
1029	    if _is_openviking_health_payload(health):
1030	        return _OPENVIKING_IDENTITY_MODERN, health
1031	    if not _is_legacy_openviking_health_payload(health):
1032	        return _OPENVIKING_IDENTITY_INVALID, health
1033
1034	    try:
1035	        openapi = client.openapi_payload()
1036	    except Exception:
1037	        logger.debug("Legacy OpenViking OpenAPI identity probe failed", exc_info=True)
1038	        return _OPENVIKING_IDENTITY_LEGACY_UNVERIFIED, health
1039	    if _is_openviking_openapi_payload(openapi):
1040	        return _OPENVIKING_IDENTITY_LEGACY, health
1041	    return _OPENVIKING_IDENTITY_LEGACY_UNVERIFIED, health
1042
1043
1044	def _legacy_openviking_identity_error(subject: str) -> str:
1045	    return f"{subject} {_LEGACY_OPENVIKING_IDENTITY_DETAIL}"
1046
1047
1048	def _load_profile(path: Path, *, source: str, name: str) -> Optional[_OvcliProfile]:
1049	    try:
1050	        data = _load_ovcli_config(path)
1051	        values = _connection_values_from_ovcli(data)
1052	    except Exception as e:
1053	        logger.warning(
1054	            "Skipping invalid OpenViking CLI config %s: %s",
1055	            path,
1056	            _format_openviking_exception(e),
1057	        )
1058	        return None
1059	    return _OvcliProfile(
1060	        source=source,
1061	        name=name,
1062	        path=path,
1063	        data=data,
1064	        values=values,
1065	    )
1066
1067
1068	def _profile_identity(path: Path) -> str:
1069	    try:
1070	        return str(path.expanduser().resolve())
1071	    except OSError:
1072	        return str(path.expanduser())
1073
1074
1075	def _profiles_equivalent(left: _OvcliProfile, right: _OvcliProfile) -> bool:
1076	    return left.values == right.values
1077
1078
1079	def _discover_ovcli_profiles() -> list[_OvcliProfile]:
1080	    profiles: list[_OvcliProfile] = []
1081	    seen_paths: set[str] = set()
1082
1083	    def add(path: Path, *, source: str, name: str) -> None:
1084	        if not path.exists() or not path.is_file():
1085	            return
1086	        identity = _profile_identity(path)
1087	        if identity in seen_paths:
1088	            return
1089	        profile = _load_profile(path, source=source, name=name)
1090	        if profile is None:
1091	            return
1092	        seen_paths.add(identity)
1093	        profiles.append(profile)
1094
1095	    env_path = os.environ.get(_OVCLI_CONFIG_ENV, "").strip()
1096	    if env_path:
1097	        add(Path(env_path).expanduser(), source="env", name=_OVCLI_CONFIG_ENV)
1098
1099	    active_path = _default_ovcli_config_path()
1100	    active_profile = _load_profile(active_path, source="active", name="active") if active_path.exists() else None
1101
1102	    config_dir = _ovcli_config_dir()
1103	    saved_start = len(profiles)
1104	    if config_dir.exists():
1105	        for path in sorted(config_dir.iterdir(), key=lambda item: item.name):
1106	            if not path.is_file():
1107	                continue
1108	            name = path.name.removeprefix(_OVCLI_SAVED_PREFIX)
1109	            if name == path.name or name == "bak" or not _is_valid_ovcli_profile_name(name):
1110	                continue
1111	            add(path, source="saved", name=name)
1112
1113	    if active_profile is not None:
1114	        marked_active = False
1115	        for idx in range(saved_start, len(profiles)):
1116	            if profiles[idx].source == "saved" and _profiles_equivalent(profiles[idx], active_profile):
1117	                profiles[idx] = replace(profiles[idx], is_active=True)
1118	                marked_active = True
1119	                break
1120	        has_env_profile = any(profile.source == "env" for profile in profiles)
1121	        has_saved_profile = any(profile.source == "saved" for profile in profiles)
1122	        active_identity = _profile_identity(active_profile.path)
1123	        if not marked_active and not has_env_profile and not has_saved_profile and active_identity not in seen_paths:
1124	            profiles.append(active_profile)
1125
1126	    return profiles
1127
1128
1129	def _is_local_openviking_url(value: str) -> bool:
1130	    try:
1131	        candidate = _normalize_openviking_url(value)
1132	    except _OpenVikingEndpointError:
1133	        return False
1134	    if not candidate:

... (gap) ...

1144	    try:
1145	        from hermes_cli.config import load_config_readonly
1146
1147	        config = load_config_readonly()
1148	        memory_config = config.get("memory", {}) if isinstance(config, dict) else {}
1149	        provider_config = memory_config.get("openviking", {}) if isinstance(memory_config, dict) else {}
1150	        return dict(provider_config) if isinstance(provider_config, dict) else {}
1151	    except Exception:
1152	        return {}
1153
1154
1155	def _env_value(name: str) -> Optional[str]:
1156	    """Profile-scoped env read; miss under multiplex is unset (never os.environ)."""
1157	    val = get_secret(name)
1158	    if val is None:
1159	        return None
1160	    return val.strip()

... (gap) ...

1171	    provider_config = dict(provider_config or {})
1172	    ovcli_values: dict = {}
1173	    if provider_config.get("use_ovcli_config"):
1174	        ovcli_path = _resolve_ovcli_config_path(str(provider_config.get("ovcli_config_path") or ""))
1175	        ovcli_values = _connection_values_from_ovcli(_load_ovcli_config(ovcli_path))
1176
1177	    endpoint_env = _env_value("OPENVIKING_ENDPOINT")
1178	    api_key_env = _env_value("OPENVIKING_API_KEY")
1179	    account_env = _env_value("OPENVIKING_ACCOUNT")
1180	    user_env = _env_value("OPENVIKING_USER")
1181	    agent_env = _env_value("OPENVIKING_AGENT")
1182
1183	    # Non-secret fields fall back to config.yaml (e.g. the Dashboard writes
1184	    # ``memory.openviking.endpoint`` there) before the built-in default, so the
1185	    # full chain is env -> ovcli -> config.yaml -> default. The secret api_key is
1186	    # sourced from the environment (synced from .env), never from config.yaml.
1187	    endpoint = _first_nonempty(
1188	        endpoint_env,
1189	        ovcli_values.get("endpoint"),
1190	        _clean_config_value(provider_config.get("endpoint")),
1191	        default=_DEFAULT_ENDPOINT,
1192	    )
1193	    return {
1194	        "endpoint": _normalize_openviking_url(endpoint),
1195	        "api_key": api_key_env if api_key_env is not None else ovcli_values.get("api_key", ""),
1196	        "account": account_env if account_env is not None else _first_nonempty(
1197	            ovcli_values.get("account"), _clean_config_value(provider_config.get("account"))
1198	        ),
1199	        "user": user_env if user_env is not None else _first_nonempty(
```


> **Explore budget: 3 calls for this project (9,014 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
