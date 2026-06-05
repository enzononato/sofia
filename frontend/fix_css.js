const fs = require('fs');
const path = require('path');

const cssPath = path.join(__dirname, 'src/app/globals.css');
let css = fs.readFileSync(cssPath, 'utf8');

// Replace all occurrences of `--var: oklch(A B C);` with `--var: A B C;`
// It also handles `--var: oklch(A B C / 10%);`
css = css.replace(/oklch\(([^)]+)\)/g, '$1');

fs.writeFileSync(cssPath, css);
console.log('Fixed globals.css');
