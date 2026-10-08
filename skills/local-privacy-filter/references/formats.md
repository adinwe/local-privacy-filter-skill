# File scope and review

The service accepts one CSV, XLSX, DOCX or PDF file at a time, up to **20 MiB**. It processes at most **100,000 extracted characters** per document. PDFs are limited to **50 pages**, including at most **20 OCR pages**. It rejects over-limit files rather than returning a truncated copy.

Outputs are freshly reconstructed filtered copies. The input remains unchanged. Copies use fixed filenames, and formats can lose structure or non-text content even when no identifiers are found.

| Format | Practical scope |
| --- | --- |
| CSV | Text cells are filtered and written into a new UTF-8 CSV. Review delimiters, column labels and values. |
| XLSX | A new workbook is built from filtered cell content. Review sheet labels and cell values. Formulas and advanced workbook features are not preserved as functioning workbook features. |
| DOCX | Extracted paragraph and table text is filtered and rebuilt into a simplified Word copy. Review content order and table structure. |
| PDF | Extracted readable text, or locally recognized scanned text, is filtered and written into a fresh text PDF. Original page layout and images are not preserved. |

Legacy `.xls` and `.doc` files need to be resaved as `.xlsx` and `.docx`. Macro-enabled, encrypted, unsupported or unreadable inputs are not supported by selecting a different extension.

## What a copy can omit

Images, drawings, embedded objects, document comments/annotations, signatures, original layout and other non-text features can be omitted. Converter warnings describe material omissions. Do not say the filtered copy preserves the entire original document.

Scanned pages use local Poppler and Tesseract when available. OCR can miss text or misread identifiers; a clean-looking result and a low detection count do not prove the source contained no personal data.

## Review

Open the created copy and check the text, placeholders and document structure before sharing. Inspect indirect identifiers and context as well as obvious names, contact details and numbers. This model targets English; Chinese or mixed-language notes need a separately evaluated detector.

Typed placeholders such as `[PERSON]` and `[EMAIL_ADDRESS]` replace detected spans. Conflicting overlapping detections can become `[SENSITIVE_DATA]`. There is no stored original-value restore map.

The UI summarizes processed parts and detected replacements. It does not automatically approve the result, save the copy or send it to another application. Confirm a file was actually saved before reporting its location.
