"""Lossless tables for repetitive position records in bounded research packets.

Every record and value remains inline. Layout integers are full-field indices;
constant fields are stored once per structural group, and rows carry only the
varying columns. This changes presentation, never the economic sample.
"""
from copy import deepcopy
from .engine import canonical, fingerprint

VERSION='position-record-table-v1'
MAX_RECORDS=200000
MAX_FIELDS=1024
MAX_RESTORED_CHARS=2000000


def compact_records(value, *, scalar_maps_as_cells=True):
    kind='mapping' if isinstance(value,dict) else 'list' if isinstance(value,list) else None
    if kind is None:return value
    items=list(value.items()) if kind=='mapping' else list(enumerate(value))
    if not 2<=len(items)<=MAX_RECORDS or any(not isinstance(row,dict) for _,row in items):return value
    groups={}
    for identity,row in items:
        fields=[]
        def layout(node,depth=0):
            if depth>16:raise ValueError('Position record layout depth exceeded')
            # Small scalar maps (notably fee-token maps) remain cells. Their
            # empty/nonempty keys must not multiply the surrounding schemas.
            if isinstance(node,dict) and (not scalar_maps_as_cells or depth==0 or any(isinstance(v,(dict,list)) for v in node.values())):
                return {key:layout(node[key],depth+1) for key in sorted(node)}
            index=len(fields);fields.append(node)
            if len(fields)>MAX_FIELDS:raise ValueError('Position record field bound exceeded')
            return index
        template=layout(row);key=canonical(template)
        groups.setdefault(key,{'layout':template,'records':[]})['records'].append((identity,fields))
    encoded=[]
    for group in groups.values():
        records=group['records'];first=records[0][1];constants={};columns=[]
        for index,cell in enumerate(first):
            if all(canonical(row[index])==canonical(cell) for _,row in records):constants[str(index)]=cell
            else:columns.append(index)
        encoded.append({'layout':group['layout'],'field_count':len(first),'constants':constants,
            'columns':columns,'rows':[[identity,[fields[i] for i in columns]] for identity,fields in records]})
    output={'projection_version':VERSION,'kind':kind,'record_count':len(items),
        'source_fingerprint':fingerprint(value),'groups':encoded}
    return output if len(canonical(output))<len(canonical(value)) else value


def restore_records(value):
    if not isinstance(value,dict) or value.get('projection_version')!=VERSION:return value
    kind=value.get('kind');count=value.get('record_count');groups=value.get('groups')
    if (kind not in ('mapping','list') or type(count) is not int or not 1<=count<=MAX_RECORDS
            or not isinstance(groups,list) or not 1<=len(groups)<=count):
        raise ValueError('Invalid bounded position record table')
    output={};seen=set();total=0;restored_chars=2
    for group in groups:
        if not isinstance(group,dict):raise ValueError('Structured position group required')
        n=group.get('field_count');constants=group.get('constants');columns=group.get('columns');rows=group.get('rows')
        if (type(n) is not int or not 0<=n<=MAX_FIELDS or not isinstance(constants,dict)
                or not isinstance(columns,list) or not isinstance(rows,list) or not rows):
            raise ValueError('Invalid position table columns')
        if any(not isinstance(key,str) or not key.isdigit() or str(int(key))!=key for key in constants):
            raise ValueError('Canonical position constant indices required')
        fixed={int(key):cell for key,cell in constants.items()}
        if (any(type(index) is not int for index in columns) or len(set(columns))!=len(columns)
                or set(fixed)&set(columns) or set(fixed)|set(columns)!=set(range(n))):
            raise ValueError('Position table columns must partition all fields')
        indices=[]
        def expand(template,fields,depth=0):
            if depth>16:raise ValueError('Position record layout depth exceeded')
            if isinstance(template,dict):return {key:expand(item,fields,depth+1) for key,item in template.items()}
            if type(template) is not int or not 0<=template<n:raise ValueError('Invalid position table layout')
            indices.append(template)
            return fields[template]
        for row in rows:
            total+=1
            if total>count or not isinstance(row,list) or len(row)!=2:raise ValueError('Position table row bound exceeded')
            identity,cells=row
            if (not isinstance(cells,list) or len(cells)!=len(columns)
                    or (kind=='mapping' and not isinstance(identity,str))
                    or (kind=='list' and (type(identity) is not int or not 0<=identity<count))
                    or identity in seen):raise ValueError('Invalid or duplicate position table row')
            seen.add(identity);fields=[None]*n
            for index,cell in fixed.items():fields[index]=deepcopy(cell)
            for index,cell in zip(columns,cells):fields[index]=deepcopy(cell)
            indices.clear();decoded=expand(group.get('layout'),fields)
            if not isinstance(decoded,dict) or sorted(indices)!=list(range(n)):
                raise ValueError('Position layout must name every field once')
            restored_chars+=len(canonical(decoded))+(len(canonical(identity))+1 if kind=='mapping' else 0)+(1 if total>1 else 0)
            if restored_chars>MAX_RESTORED_CHARS:
                raise ValueError('Position table restored-size bound exceeded')
            output[identity]=decoded
    if total!=count:raise ValueError('Position table record count mismatch')
    restored=output if kind=='mapping' else [output[index] for index in range(count)]
    if fingerprint(restored)!=value.get('source_fingerprint'):raise ValueError('Position table source fingerprint mismatch')
    return restored


def compact_position_path(path):
    if not isinstance(path,dict):return path
    out=deepcopy(path)
    for key in ('segments','ruptures'):
        if key in out:out[key]=compact_records(out[key])
    return out


def restore_position_path(path):
    if not isinstance(path,dict):return path
    out=deepcopy(path)
    for key in ('segments','ruptures'):
        if key in out:out[key]=restore_records(out[key])
    return out
