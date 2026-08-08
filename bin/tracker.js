#!/usr/bin/env node
'use strict';

// Thin launcher: runs the Python CLI (`python -m tracker`) from the package
// directory. The Python package ships inside this npm package; only the web
// dependencies (fastapi/uvicorn) need `pip install -r requirements.txt` for
// the `serve` command — the CLI prints a clear message if they are missing.
const { spawn } = require('child_process');
const path = require('path');

const pkgDir = path.join(__dirname, '..');
const python = process.env.TRACKER_PYTHON || 'python';
const args = ['-m', 'tracker', ...process.argv.slice(2)];

const child = spawn(python, args, { cwd: pkgDir, stdio: 'inherit' });
child.on('error', (err) => {
  if (err.code === 'ENOENT') {
    console.error(
      `Cannot find Python (${python}). Install Python 3.11+ or set TRACKER_PYTHON.`
    );
  } else {
    console.error(`Failed to start tracker: ${err.message}`);
  }
  process.exit(1);
});
child.on('exit', (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0));
});