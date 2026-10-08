# Release verification

## v1.0.1 — Codex and Claude Code installation

The same source skill is packaged for local Codex and Claude Code sessions. The added Claude Code launcher selects its personal skill directory; the existing Codex launcher and custom destination option remain available.

- Both agent installers copied exactly 31 source skill files into isolated directories with spaces; backups preserved the previous installation, and executable permissions were retained.
- Nine invalid argument cases returned errors before creating files. Help, custom destination overrides, flag order, default destination selection and launcher syntax were checked without changing actual user skill folders.
- No model weights, environments or caches were copied. Skill validation and documentation reference checks passed, and independent review found no release blocker.

The local filter application, pinned dependencies, model downloads and seven fictional input files are unchanged from v1.0.0. The application evidence below remains applicable. Actual use inside a Claude Code session and a complete first-time installation on a fresh Mac have not been tested.

## v1.0.0 — application and setup verification

Verified on 8 October 2026 for macOS Apple Silicon.

- All **76 tests** passed: 58 application tests plus 18 installer tests.
- Skill frontmatter/UI metadata validation and relative reference links passed.
- Independent forward testing copied the skill to an isolated path containing spaces. Network-blocked check-only mode created no model, environment or cache files and left the package unchanged.
- The packaged start/check helpers launched an isolated local app, verified app/workspace identity and passed their fixed fictional contact smoke test.
- That packaged app filtered the 7,545-character fictional Word case note with the real GLiNER2/Presidio engine. Test identifiers at the start and end were removed, original bytes were unchanged, and the generated Word file was inspected.
- Seven synthetic input files match their known fixture hashes. The source inventory contains no installed environment, downloaded model weights, compiled Python files, personal paths or credentials.
- All six public model asset size/SHA-256 pins match the previously verified installed model.

The live packaged check reused already-installed dependencies and model assets through read-only test links to avoid downloading another copy. A complete first-time installation on a colleague's machine has not been performed. Installer behavior is covered by preflight, read-only, preservation, resumability and checksum tests.

The application's earlier real-model file checks covered CSV, XLSX, DOCX, long-case-note DOCX, readable PDF, scanned PDF and mixed text/image PDF. Runtime application code in this release is the same verified implementation.

These are synthetic functional checks. They do not prove that all identifiers will be detected in real or clinical records; human review remains necessary.
