import re
class UniversalSymbolExtractor:
    TOKEN=re.compile(r"\b[A-Z]{2,8}(?:[._-](?:PRO|RAW|ECN|STD|M|A))?\b",re.I)
    def __init__(self,registry):self.registry=registry
    def extract(self,text):
        found=[];seen=set()
        for token in self.TOKEN.findall(str(text).upper()):
            try:x=self.registry.resolve(token)
            except ValueError:continue
            if x.canonical_id not in seen:found.append(x);seen.add(x.canonical_id)
        return found
