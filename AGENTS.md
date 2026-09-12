# Repository Instructions

## Post-development deployment

After completing any development change, always run the release installation flow:

```bash
./scripts/install-app.sh
```

The script closes all running Codex Switcher instances before building, runs
`./scripts/build-release.sh`, moves existing installations to Trash, moves (not
copies) `build/release/Codex Switcher.app` directly into `/Applications`, and
then starts the installed app. The release ZIP is a distribution asset only and
must never be extracted for local installation. After a successful install, no
app bundle may remain under `build/` or `~/Applications`; this prevents duplicate
Spotlight results. Existing installations remain recoverable from Trash.
