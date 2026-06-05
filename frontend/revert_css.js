const fs = require('fs');
const path = require('path');

const cssPath = path.join(__dirname, 'src/app/globals.css');
let css = fs.readFileSync(cssPath, 'utf8');

// Put oklch back for colors
css = css.replace(/--(?!font)[a-z0-9-]+: ([0-9.]+\s+[0-9.]+\s+[0-9.]+(?:\s+\/\s+[0-9.%]+)?);/g, (match, p1) => {
    return match.replace(p1, `oklch(${p1})`);
});

// Fix line 87
css = css.replace(/outline-color: var\(--ring \/ 0\.5\);/g, 'outline-color: oklch(var(--ring) / 0.5);');

fs.writeFileSync(cssPath, css);
console.log('Reverted globals.css');
