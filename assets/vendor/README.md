# Vendored, so the site runs without a CDN

| Package | Version | Licence | Used for |
|---|---|---|---|
| [Pyodide](https://pyodide.org) | 0.27.7 (core, from npm) | MPL-2.0 | Running the repository's pure-Python code in the browser |
| [CodeMirror](https://codemirror.net/5/) | 5.65.16 | MIT (`codemirror/LICENSE`) | The code editor on `run.html` |
| [js-yaml](https://github.com/nodeca/js-yaml) | 4.1.0 | MIT (`js-yaml.LICENSE`) | `yaml.safe_load` inside Pyodide |
