@ECHO OFF
REM Command file for Sphinx documentation (Windows fallback)

pushd %~dp0

set SPHINXOPTS=-W --keep-going
set SPHINXBUILD=sphinx-build

if "%1" == "" goto help
if "%1" == "clean" goto clean
if "%1" == "html" goto html
if "%1" == "serve" goto serve

%SPHINXBUILD% -M %1 . _build %SPHINXOPTS%
goto end

:help
%SPHINXBUILD% -M help . _build %SPHINXOPTS%

:clean
rmdir /s /q _build

:html
%SPHINXBUILD% -M html . _build %SPHINXOPTS%
echo.
echo Build finished. Open _build\html\index.html in a browser.

:serve
%SPHINXBUILD% -M html . _build %SPHINXOPTS%
echo.
echo Open http://localhost:8000 with: python -m http.server -d _build\html

:end
popd
