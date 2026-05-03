"""Check name entry format in Abyss.bsm."""
import struct

abyss_path = r'D:\SteamLibrary\steamapps\common\BioShock 2 Remastered\ContentBaked\pc\Maps\Abyss.bsm'
with open(abyss_path, 'rb') as f:
    data = f.read()

name_count = struct.unpack_from('<I', data, 12)[0]
name_offset = struct.unpack_from('<I', data, 16)[0]

# Parse first 5 name entries
pos = name_offset
for i in range(5):
    length = data[pos]; pos += 1
    if length == 0:
        flags = data[pos:pos+8]
        pos += 8
        print('name[%d]: length=0  flags=%s' % (i, ' '.join('%02x' % b for b in flags)))
    else:
        text_bytes = data[pos:pos+length*2]
        pos += length * 2
        flags = data[pos:pos+8]
        pos += 8
        text = text_bytes.decode('utf-16-le', errors='replace').rstrip('\x00')
        print('name[%d]: len=%d text="%s" flags=%s' % (i, length, text, ' '.join('%02x' % b for b in flags)))

# Check Core (12819) and Emitter (1537)
pos = name_offset
for i in range(12820):
    l = data[pos]; pos += 1
    if l == 0:
        pos += 8
    else:
        pos += l * 2 + 8
    if i in (1536, 12818):
        l2 = data[pos]
        text = data[pos+1:pos+1+l2*2].decode('utf-16-le', errors='replace').rstrip('\x00')
        fl = data[pos+1+l2*2:pos+1+l2*2+8]
        print('name[%d]: len=%d text="%s" flags=%s' % (i+1, l2, text, ' '.join('%02x' % b for b in fl)))
