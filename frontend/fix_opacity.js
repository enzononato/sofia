const fs = require('fs');
const path = require('path');

function replaceOpacity(filePath) {
    let content = fs.readFileSync(filePath, 'utf8');

    // Replace bg-background/50 -> bg-[color-mix(in_oklch,var(--background)_50%,transparent)]
    content = content.replace(/bg-background\/50/g, 'bg-[color-mix(in_oklch,var(--background)_50%,transparent)]');
    content = content.replace(/bg-primary\/20/g, 'bg-[color-mix(in_oklch,var(--primary)_20%,transparent)]');
    content = content.replace(/ring-primary\/30/g, 'ring-[color-mix(in_oklch,var(--primary)_30%,transparent)]');
    content = content.replace(/shadow-primary\/20/g, 'shadow-[color-mix(in_oklch,var(--primary)_20%,transparent)]');
    content = content.replace(/bg-destructive\/10/g, 'bg-[color-mix(in_oklch,var(--destructive)_10%,transparent)]');

    fs.writeFileSync(filePath, content);
}

replaceOpacity(path.join(__dirname, 'src/app/login/page.tsx'));
replaceOpacity(path.join(__dirname, 'src/app/signup/page.tsx'));
replaceOpacity(path.join(__dirname, 'src/app/globals.css'));

console.log('Fixed opacities');
