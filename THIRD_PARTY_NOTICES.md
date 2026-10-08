# Third-party components

The repository's MIT license covers its original application, skill and helper code. Model weights, Python distributions, native tools and fonts retain their upstream licenses. They are downloaded or installed separately; this source repository does not vendor their binaries or model weights.

Preserve the licenses and notices included in installed distributions and model downloads. The full Python dependency set is pinned in `skills/local-privacy-filter/assets/app/requirements.lock.txt`; the table below identifies the principal components used by the app.

| Component | Pinned version or revision | Upstream license | Source |
| --- | --- | --- | --- |
| GLiNER2 | 2.0.0 | Apache-2.0 | [Fastino GLiNER2](https://github.com/fastino-ai/GLiNER2) |
| GLiNER2 PII model | `1cb4166094dc58fa8d836429f060d6c95f62b495` | Apache-2.0 | [Model repository](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi/tree/1cb4166094dc58fa8d836429f060d6c95f62b495) |
| Presidio analyzer and anonymizer | 2.2.364 | MIT | [Presidio](https://github.com/data-privacy-stack/presidio) |
| spaCy | 3.8.16 | MIT | [spaCy](https://github.com/explosion/spaCy) |
| English spaCy model | en_core_web_sm 3.8.0 | MIT | [Model release](https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0) |
| openpyxl | 3.1.5 | MIT | [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) |
| python-docx | 1.2.0 | MIT | [python-docx](https://github.com/python-openxml/python-docx) |
| pypdf | 6.19.0 | BSD-3-Clause | [pypdf](https://github.com/py-pdf/pypdf) |
| ReportLab | 5.0.1 | BSD | [ReportLab](https://www.reportlab.com/) |
| Pillow | 12.3.0 | MIT-CMU | [Pillow](https://github.com/python-pillow/Pillow) |
| defusedxml | 0.7.1 | PSFL | [defusedxml](https://github.com/tiran/defusedxml) |
| Poppler, optional local OCR dependency | Installed through the user's native package manager | GPL-2.0-only | [Poppler](https://poppler.freedesktop.org/) |
| Tesseract, optional local OCR dependency | Installed through the user's native package manager | Apache-2.0 | [Tesseract](https://github.com/tesseract-ocr/tesseract) |

ReportLab's installed `Vera.ttf` has a separate Bitstream Vera font license, included in the distribution as `fonts/bitstream-vera-license.txt`. Fonts are not copied into this repository.

The setup tools also use [uv](https://github.com/astral-sh/uv) and managed [Python](https://www.python.org/). Their licenses and downloaded package notices remain applicable. Transitive Python dependencies keep the license files included in their installed distributions; the original source license does not replace those terms.
