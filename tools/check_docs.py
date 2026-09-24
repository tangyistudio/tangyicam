"""Check relative documentation/demo assets without network or build dependencies."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
ROOT=Path(__file__).resolve().parents[1]
paths=[ROOT/'README.md',ROOT/'README.zh-TW.md',*ROOT.joinpath('docs').glob('*.md'),*ROOT.joinpath('docs').rglob('index.html')]
for path in paths:
 text=path.read_text(encoding='utf-8')
 links=re.findall(r'(?:href|src)=[\"\']([^\"\']+)',text) if path.suffix=='.html' else re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)|!\[[^\]]*\]\(([^)]+)\)',text)
 for match in links:
  link=next((x for x in match if x),'') if isinstance(match,tuple) else match
  parts=urlsplit(link)
  if parts.scheme or link.startswith('#') or not parts.path:continue
  target=(path.parent/unquote(parts.path)).resolve()
  assert target.is_relative_to(ROOT),f'Link outside repository: {path}: {link}'
  assert target.exists(),f'Missing link: {path}: {link}'
print('DOC_LINKS_PASS',len(paths))
