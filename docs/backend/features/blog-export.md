# Completed blog export

The authenticated endpoint `GET /api/v1/blogs/{session_id}/export?format=pdf|docx`
exports the latest saved Markdown version for a session owned by the current
user. It only returns a file when the session status is `COMPLETED`.

The endpoint is additive and does not change blog generation or the existing
content response. It returns `application/pdf` for PDF and the standard DOCX
media type for Word documents. An unfinished session returns `409`; an unknown
or non-owned session returns `404`.

## Runtime requirements

The Python dependency `pypandoc` is installed with the backend. The backend
container also installs the Pandoc executable for both formats and XeLaTeX as
the PDF engine. PDF export returns `503` with a clear message if these runtime
tools are unavailable. The deployment workflow checks for both executables in
the running API container after deployment. No binary download is attempted
while handling a user request.

The generated file is written to a temporary directory and removed after the
response is sent.
