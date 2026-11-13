"""Bound agent telemetry before retaining or rendering it."""
import math

TEXT = ('hostname fqdn primary_ip os kernel name ipv4 protocol family local_ip remote_ip state service time source_ip username event message host scope').split()
NUMBER = ('timestamp cpu_percent cpu_count cpu_physical cpu_frequency_mhz load_1 load_5 load_15 memory_percent memory_used memory_total memory_available swap_percent swap_used swap_total disk_percent disk_used disk_total disk_free uptime speed_mbps mtu rx_rate tx_rate rx_total tx_total packets_recv packets_sent errors_in errors_out drops_in drops_out local_port remote_port source_port target_port port observations connection_count listener_count failed_login_count captured_at memory_percent').split()
TOP = set('timestamp hostname fqdn primary_ip os kernel cpu_percent cpu_count cpu_physical cpu_frequency_mhz load_1 load_5 load_15 memory_percent memory_used memory_total memory_available swap_percent swap_used swap_total disk_percent disk_used disk_total disk_free uptime interfaces processes network_intel'.split())
INTEL = set('captured_at scope connections connection_count listeners listener_count frequent_ports failed_logins failed_login_count log_sources limitations'.split())
ARRAYS = {
    'interfaces': (64, set('name ipv4 is_up speed_mbps mtu rx_rate tx_rate rx_total tx_total packets_recv packets_sent errors_in errors_out drops_in drops_out'.split())),
    'processes': (8, {'pid', 'name', 'user', 'memory_percent'}),
    'connections': (250, set('protocol family local_ip local_port remote_ip remote_port state pid'.split())),
    'listeners': (150, set('protocol family local_ip local_port remote_ip remote_port state pid service'.split())),
    'frequent_ports': (20, {'protocol', 'port', 'service', 'observations'}),
    'failed_logins': (100, set('time source_ip source_port service target_port username event message'.split())),
}


def validate(data):
    def obj(value, allowed, depth=0):
        if not isinstance(value, dict) or not set(value).issubset(allowed) or depth > 3:
            raise ValueError('Invalid telemetry object')
        for key, item in value.items():
            if key == 'network_intel':
                obj(item, INTEL, depth + 1)
            elif key in ARRAYS:
                limit, fields = ARRAYS[key]
                if not isinstance(item, list) or len(item) > limit:
                    raise ValueError('Invalid telemetry array')
                for entry in item:
                    obj(entry, fields, depth + 1)
            elif key in ('log_sources', 'limitations'):
                if not isinstance(item, list) or len(item) > 16 or any(not isinstance(x, str) or len(x) > 256 for x in item):
                    raise ValueError('Invalid telemetry text array')
            elif key == 'is_up':
                if not isinstance(item, bool):
                    raise ValueError('Invalid boolean')
            elif key == 'pid':
                if item is not None and (type(item) is not int or not 0 <= item <= 2**32):
                    raise ValueError('Invalid process ID')
            elif key in TEXT or key == 'user':
                if not isinstance(item, str) or len(item) > 256 or any(ord(c) < 32 for c in item):
                    raise ValueError('Invalid telemetry string')
            elif key in NUMBER:
                if type(item) not in (int, float) or not math.isfinite(item) or not 0 <= item <= 2**64:
                    raise ValueError('Invalid telemetry number')
                if key.endswith('_percent') and item > 100:
                    raise ValueError('Invalid percentage')
                if key in ('port', 'local_port', 'remote_port', 'source_port', 'target_port') and (type(item) is not int or item > 65535):
                    raise ValueError('Invalid port')
            else:
                raise ValueError('Unknown telemetry field')
    obj(data, TOP)
    if not isinstance(data.get('hostname'), str) or not data['hostname']:
        raise ValueError('Hostname required')
    return data


def sanitize_local(value, key=''):
    """Bound OS-provided strings/counts to the same contract used for agents."""
    if isinstance(value, dict):
        return {k: sanitize_local(v, k) for k, v in value.items()}
    if isinstance(value, list):
        limit=ARRAYS[key][0] if key in ARRAYS else 16
        return [sanitize_local(v) for v in value[:limit]]
    if isinstance(value, str):
        return ''.join(c if ord(c)>=32 else ' ' for c in value)[:256]
    if type(value) in (int,float):
        if not math.isfinite(value): return 0
        return max(0,min(value,100 if key.endswith('_percent') else 2**64))
    return value
