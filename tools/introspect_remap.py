import unreal

s = unreal.PCGAttributeRemapSettings()
print("REMAP PROPS:", [n for n in dir(s) if "range" in n.lower() or "remap" in n.lower()])
