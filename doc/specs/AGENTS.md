# Specification handling rules

1. Preserve local specification files; move them without altering their contents.
2. Do not stage or publish a specification payload unless the operator explicitly authorizes publishing that specific file.
3. Keep the class policy files tracked and verify that specification payloads remain ignored by `.gitignore`.
4. Do not store credentials or session dumps in this class.
