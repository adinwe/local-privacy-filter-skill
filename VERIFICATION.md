# Release verification — v1.0.0

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
