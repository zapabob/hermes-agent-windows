**Exploration: gateway/platform_registry.py**

Found 24 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`gateway/platform_registry.py`** — calls(calls), get(calls), _scope_maps(calls), current_scope_key(calls), _resolve(calls), _plugin_scope_from_callable(calls), _caller_plugin_scope(calls), _resolve_all(calls), logger(variable), _plugin_scope_from_callable(function), _caller_plugin_scope(function), PlatformEntry(class), __init__(method), current_scope_key(method), _scope_maps(method), +17 more

```python
36
37	from hermes_constants import hermes_home_key
38
39	logger = logging.getLogger(__name__)
40
41
42	def _plugin_scope_from_callable(callback: Callable) -> Optional[str]:
43	    """Infer a plugin profile from code registered outside PluginContext."""
44	    try:
45	        from tools.registry import registry as tool_registry
46
47	        return tool_registry.plugin_scope_for_callable(callback)
48	    except (ImportError, AttributeError):
49	        return None
50
51
52	def _caller_plugin_scope() -> Optional[str]:
53	    try:
54	        module_name = sys._getframe(2).f_globals.get("__name__", "") or ""
55	    except Exception:
56	        return None
57	    return _plugin_scope_from_callable(
58	        type("_Caller", (), {"__module__": module_name})
59	    )
60
61
62	@dataclass

... (gap) ...

270	        ] = {}
271
272	    @staticmethod
273	    def current_scope_key() -> str:
274	        return hermes_home_key()
275
276	    def _scope_maps(
277	        self,
278	        scope: Optional[str],
279	        *,
280	        create: bool = False,
281	    ) -> tuple[dict[str, PlatformEntry], dict[str, Callable[[], None]]]:
282	        if scope is None:
283	            return self._entries, self._deferred
284	        if create:
285	            return (
286	                self._scoped_entries.setdefault(scope, {}),
287	                self._scoped_deferred.setdefault(scope, {}),
288	            )
289	        return (
290	            self._scoped_entries.get(scope, {}),
291	            self._scoped_deferred.get(scope, {}),
292	        )
293
294	    # -- deferred loading ----------------------------------------------------
295
296	    def register_deferred(
297	        self,
298	        name: str,
299	        loader: Callable[[], None],
300	        *,
301	        scope: Optional[str] = None,
302	    ) -> None:
303	        """Register a lazy loader for a platform that hasn't been imported yet.
304
305	        *loader* is a zero-arg callable that imports the owning plugin module,
306	        which is expected to call :meth:`register` with the real entry for
307	        *name*.  The loader runs at most once, the first time *name* is looked
308	        up (or when the full entry list is materialized).  A real entry that is
309	        registered directly (e.g. a built-in) takes precedence -- the deferred
310	        loader is then dropped.
311	        """
312	        with self._lock:
313	            entries, deferred = self._scope_maps(scope, create=True)
314	            self._consumed_loaders.pop((scope, name), None)
315	            if name in entries:
316	                # Already concretely registered; no need to defer.
317	                return
318	            deferred[name] = loader
319
320	    def snapshot_registration(
321	        self,
322	        name: str,
323	        *,
324	        scope: Optional[str] = None,
325	    ) -> tuple[Optional[PlatformEntry], Optional[Callable[[], None]]]:
326	        """Return the concrete and deferred state for *name* without resolving it.
327
328	        This host-facing snapshot lets the plugin ledger restore a deferred
329	        platform loader that a concrete registration displaced, without
330	        importing the displaced adapter as a side effect of taking the
331	        snapshot.
332	        """
333	        with self._lock:
334	            entries, deferred = self._scope_maps(scope)
335	            loader = deferred.get(name)
336	            if entries.get(name) is None and loader is None:
337	                loader = self._inflight_loaders.get((scope, name))
338	            if entries.get(name) is None and loader is None:
339	                loader = self._consumed_loaders.get((scope, name))
340	            return entries.get(name), loader
341
342	    def restore_registration(
343	        self,

... (gap) ...

355	        the state because bundled platform plugins load lazily.
356	        """
357	        with self._lock:
358	            entries, deferred = self._scope_maps(scope, create=True)
359	            entry = entries.get(name)
360	            loader = deferred.get(name)
361	            load_key = (scope, name)
362	            if entry is None and loader is None:
363	                loader = self._inflight_loaders.get(load_key)
364	            if entry is None and loader is None:
365	                loader = self._consumed_loaders.get(load_key)
366	            current_state = (entry, loader)
367	            is_current = not (
368	                current_state[0] is not current[0]

... (gap) ...

381	            else:
382	                deferred[name] = previous_loader
383	            if load_key in self._inflight:
384	                self._cancelled_inflight.add(load_key)
385	            self._consumed_loaders.pop(load_key, None)
386	            if scope is not None:
387	                if not entries:
388	                    self._scoped_entries.pop(scope, None)
389	                if not deferred:
390	                    self._scoped_deferred.pop(scope, None)
391	            return True
392
393	    def _resolve(self, name: str, scope: Optional[str] = None) -> None:
394	        """Run the deferred loader for *name* if one is pending."""
395	        loader: Optional[Callable[[], None]] = None
396	        event: Optional[threading.Event] = None
397	        load_key: tuple[Optional[str], str]
398	        is_loader = False
399	        with self._lock:
400	            active_scope = scope or self.current_scope_key()
401	            entries, deferred = self._scope_maps(active_scope)
402	            scoped_key = (active_scope, name)
403	            global_key = (None, name)
404	            event = self._inflight.get(scoped_key)
405	            load_key = scoped_key
406	            if event is None and name not in entries:
407	                loader = deferred.pop(name, None)
408	            if event is None and loader is None and name not in entries:
409	                event = self._inflight.get(global_key)
410	                load_key = global_key
411	            if event is None and loader is None and name not in entries:
412	                loader = self._deferred.pop(name, None)
413	                load_key = global_key
414	            if event is None and loader is not None:
415	                event = threading.Event()
416	                self._inflight[load_key] = event
417	                self._inflight_loaders[load_key] = loader
418	                self._inflight_owners[load_key] = threading.get_ident()
419	                is_loader = True
420	            if event is None:
421	                return
422	            if (
423	                not is_loader
424	                and self._inflight_owners.get(load_key) == threading.get_ident()
425	            ):
426	                logger.warning(
427	                    "Deferred platform '%s' recursively requested while loading",
428	                    name,
429	                )
430	                return
431
432	        if not is_loader:
433	            event.wait()
434	            # Teardown may have restored an older deferred generation while
435	            # cancelling the one we waited for. Resolve that predecessor in
436	            # the same lookup instead of returning a one-shot false negative.
437	            self._resolve(name, active_scope)
438	            return
439
440	        try:
441	            loader()
442	        except Exception as e:
443	            logger.warning(
444	                "Deferred load of platform '%s' failed: %s",
445	                name,
446	                e,
447	                exc_info=True,
448	            )
449	        finally:
450	            with self._lock:
451	                was_cancelled = load_key in self._cancelled_inflight
452	                load_scope, _load_name = load_key
453	                entries, deferred = self._scope_maps(load_scope)
454	                if (
455	                    not was_cancelled
456	                    and name not in entries
457	                    and name not in deferred
458	                ):
459	                    self._consumed_loaders[load_key] = loader
460	                self._inflight.pop(load_key, None)
461	                self._inflight_loaders.pop(load_key, None)
462	                self._inflight_owners.pop(load_key, None)
463	                self._cancelled_inflight.discard(load_key)
464	                event.set()
465	        if was_cancelled:
466	            self._resolve(name, active_scope)
467
468	    def is_deferred_load_cancelled(
469	        self,
470	        name: str,
471	        *,
472	        scope: Optional[str] = None,
473	    ) -> bool:
474	        """Return whether ownership teardown cancelled an in-flight loader."""
475	        with self._lock:
476	            return (scope, name) in self._cancelled_inflight
477
478	    def _resolve_all(self) -> None:
479	        """Run every pending deferred loader.
480
481	        Used by the iterate-all accessors (``all_entries``/``plugin_entries``),
482	        which are only called by paths that genuinely need every adapter:
483	        gateway startup, ``hermes setup``/``gateway status``, channel
484	        directory.  CLI chat never iterates the full set.
485	        """
486	        active_scope = self.current_scope_key()
487	        with self._lock:
488	            _entries, scoped_deferred = self._scope_maps(active_scope)
489	            scoped_names = set(scoped_deferred)
490	            global_names = set(self._deferred)
491	            for inflight_scope, name in self._inflight:
492	                if inflight_scope == active_scope:
493	                    scoped_names.add(name)
494	                elif inflight_scope is None:
495	                    global_names.add(name)
496	        # Load outside the registry lock; each name has an in-flight event so
497	        # concurrent readers wait for the same materialization.
498	        for name in sorted(scoped_names):
499	            self._resolve(name, active_scope)
500	        for name in sorted(global_names):
501	            self._resolve(name, active_scope)
502
503	    def register(
504	        self,
505	        entry: PlatformEntry,
506	        *,
507	        scope: Optional[str] = None,
508	    ) -> None:
509	        """Register a platform adapter entry.
510
511	        If an entry with the same name exists, it is replaced (last writer
512	        wins -- this lets plugins override built-in adapters if desired).
513	        """
514	        with self._lock:
515	            if scope is None and entry.source == "plugin":
516	                scope = _caller_plugin_scope()
517	                if scope is None:
518	                    scope = _plugin_scope_from_callable(entry.adapter_factory)
519	                if scope is None:
520	                    scope = _plugin_scope_from_callable(entry.check_fn)
521	            # A concrete registration supersedes any pending deferred loader.
522	            entries, deferred = self._scope_maps(scope, create=True)
523	            self._consumed_loaders.pop((scope, entry.name), None)
524	            deferred.pop(entry.name, None)
525	            if entry.name in entries:
526	                prev = entries[entry.name]
527	                logger.info(
528	                    "Platform '%s' re-registered (was %s, now %s)",
529	                    entry.name,
530	                    prev.source,
531	                    entry.source,
532	                )
533	            entries[entry.name] = entry
534	            logger.debug("Registered platform adapter: %s (%s)", entry.name, entry.source)
535
536	    def unregister(self, name: str, *, scope: Optional[str] = None) -> bool:
537	        """Remove a platform entry.  Returns True if it existed."""
538	        with self._lock:
539	            inferred_scope = scope if scope is not None else _caller_plugin_scope()
540	            active_scope = inferred_scope or self.current_scope_key()
541	            entries, deferred = self._scope_maps(active_scope)
542	            if inferred_scope is not None or name in entries or name in deferred:
543	                deferred.pop(name, None)
544	                removed = entries.pop(name, None) is not None
545	                if not entries:
546	                    self._scoped_entries.pop(active_scope, None)
547	                if not deferred:
548	                    self._scoped_deferred.pop(active_scope, None)
549	                return removed
550	            self._deferred.pop(name, None)
551	            return self._entries.pop(name, None) is not None
552
553	    def get(self, name: str) -> Optional[PlatformEntry]:
554	        """Look up a platform entry by name."""
555	        scope = self.current_scope_key()
556	        with self._lock:
557	            entries, deferred = self._scope_maps(scope)
558	            needs_resolve = name not in entries and (
559	                name in deferred
560	                or (name not in self._entries and name in self._deferred)
561	                or (scope, name) in self._inflight
562	                or (None, name) in self._inflight
563	            )
564	        if needs_resolve:
565	            self._resolve(name, scope)
566	        with self._lock:
567	            entries, _deferred = self._scope_maps(scope)
568	            return entries.get(name) or self._entries.get(name)
569
570	    def all_entries(self) -> list[PlatformEntry]:
571	        """Return all registered platform entries."""
572	        self._resolve_all()
573	        with self._lock:
574	            entries = dict(self._entries)
575	            entries.update(self._scoped_entries.get(self.current_scope_key(), {}))
576	            return list(entries.values())
577
578	    def required_env_names(self, *, include_profile: bool = True) -> frozenset[str]:
579	        """Read concrete declarations without executing deferred loaders."""
580	        with self._lock:
581	            entries = list(self._entries.values())
582	            if include_profile:
583	                entries.extend(self._scoped_entries.get(self.current_scope_key(), {}).values())
584	            names: set[str] = set()
585	            for entry in entries:
586	                if not isinstance(entry.required_env, (list, tuple, set, frozenset)) or any(
587	                    not isinstance(name, str) or not name.strip() for name in entry.required_env
588	                ):
589	                    raise RuntimeError("Invalid platform credential declaration")
590	                names.update(entry.required_env)
591	            return frozenset(names)
592
593	    def plugin_entries(self) -> list[PlatformEntry]:
594	        """Return only plugin-registered platform entries."""
595	        self._resolve_all()
596	        return [e for e in self.all_entries() if e.source == "plugin"]
597
598	    def registered_names(self) -> set[str]:
599	        """Return concrete and deferred platform names without loading adapters.
600
601	        Mirrors ``is_registered()``'s scope semantics: names registered under
602	        the current profile scope AND process-global names both count. Plugin
603	        platforms register deferred loaders under a profile scope, so reading
604	        only the global maps would miss every plugin platform.
605	        """
606	        with self._lock:
607	            scope = self.current_scope_key()
608	            entries, deferred = self._scope_maps(scope)
609	            return (
610	                entries.keys()
611	                | deferred.keys()
612	                | self._entries.keys()
613	                | self._deferred.keys()
614	            )
615
616	    def is_registered(self, name: str) -> bool:
617	        # A deferred (not-yet-imported) platform still counts as registered --
618	        # the loader will materialize it on first real use.  This keeps cheap
619	        # membership checks (toolset resolution, webhook deliver-target checks)
620	        # from triggering a heavy import.
621	        with self._lock:
622	            scope = self.current_scope_key()
623	            entries, deferred = self._scope_maps(scope)
624	            return (
625	                name in entries
626	                or name in deferred
627	                or name in self._entries
628	                or name in self._deferred
629	                or (scope, name) in self._inflight
630	                or (None, name) in self._inflight
631	            )
632
633	    def create_adapter(self, name: str, config: Any) -> Optional[Any]:
634	        """Create an adapter instance for the given platform name.
635
636	        Returns None if:
637	        - No entry registered for *name*
638	        - check_fn() returns False and deps can't be installed
639	          (no ensure_deps_fn, or ensure_deps_fn() returned False)
640	        - validate_config() returns False (misconfigured)
641	        - The factory raises an exception
642	        """
643	        entry = self.get(name)
644	        if entry is None:
645	            return None
646
647	        deps_ok = False
648	        try:
649	            deps_ok = bool(entry.check_fn())
650	        except Exception as e:
651	            logger.warning(
652	                "Platform '%s' check_fn raised: %s", entry.label, e
653	            )
654	        if not deps_ok and entry.ensure_deps_fn is not None:

... (gap) ...

665	            try:
666	                deps_ok = bool(entry.ensure_deps_fn())
667	            except Exception as e:
668	                logger.warning(
669	                    "Platform '%s' dependency install raised: %s",
670	                    entry.label,
671	                    e,
672	                )
673	                deps_ok = False
674	        if not deps_ok:
675	            hint = f" ({entry.install_hint})" if entry.install_hint else ""
676	            logger.warning(
677	                "Platform '%s' requirements not met%s",
678	                entry.label,
679	                hint,
680	            )
681	            return None
682
683	        if entry.validate_config is not None:
684	            try:
685	                if not entry.validate_config(config):
686	                    logger.warning(
687	                        "Platform '%s' config validation failed",
688	                        entry.label,
689	                    )
690	                    return None
691	            except Exception as e:
692	                logger.warning(
693	                    "Platform '%s' config validation error: %s",
694	                    entry.label,
695	                    e,

... (gap) ...

710
711
712	# Module-level singleton
713	platform_registry = PlatformRegistry()
714
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,021 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
