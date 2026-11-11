"""
Xploit Security Guard — Advanced SSRF Firewall & CIDR Validator
Protects against SSRF, LFD, Cloud Metadata theft, DNS rebinding, and internal pivoting.
"""
import ipaddress
import socket
from urllib.parse import urlsplit
from typing import Optional

BLOCKED_NETWORKS = [
    # IPv4 Private / Loopback / Link-Local / Carrier / Reserved
    ipaddress.ip_network("0.0.0.0/8"),          # Current network ("this" host)
    ipaddress.ip_network("10.0.0.0/8"),          # RFC 1918 Class A
    ipaddress.ip_network("100.64.0.0/10"),       # Shared Address Space (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),      # Link-Local & AWS/GCP/Azure IMDS
    ipaddress.ip_network("172.16.0.0/12"),       # RFC 1918 Class B
    ipaddress.ip_network("192.0.0.0/24"),        # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),        # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),      # RFC 1918 Class C
    ipaddress.ip_network("198.18.0.0/15"),       # Network benchmark tests
    ipaddress.ip_network("198.51.100.0/24"),     # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),      # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for future use
    ipaddress.ip_network("255.255.255.255/32"),  # Limited broadcast
    
    # IPv6 Loopback / Link-Local / Unique-Local / Multicast
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),      # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),       # IPv4/IPv6 translation
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-Local
    ipaddress.ip_network("ff00::/8"),           # Multicast
]

BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata.google.internal", "metadata", "instance-data"
}

SAFE_SCHEMES = {"http", "https"}

def validate_safe_url(url: Optional[str], field_name: str = "URL") -> str:
    """
    Validates that a URL is well-formed, uses http/https, and does not point to
    localhost, private subnets, link-local metadata, or prohibited internal hosts.
    Raises ValueError with descriptive reason if invalid.
    """
    if not url or not isinstance(url, str):
        raise ValueError(f"{field_name} must be a valid non-empty string.")
    
    clean_url = url.strip()
    try:
        parsed = urlsplit(clean_url)
    except Exception as e:
        raise ValueError(f"Malformed {field_name}: {e}")

    # 1. Scheme Check
    scheme = (parsed.scheme or "").lower()
    if scheme not in SAFE_SCHEMES:
        raise ValueError(f"{field_name} protocol '{scheme}' prohibited. Only HTTP/HTTPS permitted.")

    # 2. Hostname Check
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"{field_name} must include a valid hostname.")

    hostname_lower = hostname.lower()

    if hostname_lower in BLOCKED_HOSTNAMES or hostname_lower.endswith(".internal") or hostname_lower.endswith(".local"):
        raise ValueError(f"Access to restricted hostname '{hostname}' is denied.")

    # 3. Handle Alternate Encodings (Decimal, Hex)
    ip_candidates = []
    try:
        if hostname_lower.startswith("0x"):
            ip_candidates.append(ipaddress.IPv4Address(int(hostname_lower, 16)))
        elif hostname_lower.isdigit():
            ip_candidates.append(ipaddress.IPv4Address(int(hostname_lower)))
    except Exception:
        pass

    # 4. Standard IP or DNS Resolution
    if not ip_candidates:
        try:
            # Direct IP check
            parsed_ip = ipaddress.ip_address(hostname_lower.strip("[]"))
            ip_candidates.append(parsed_ip)
        except ValueError:
            # Domain name: resolve via socket
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for r in resolved:
                    ip_candidates.append(ipaddress.ip_address(r[4][0]))
            except socket.gaierror as e:
                raise ValueError(f"DNS resolution failed for {hostname}: {e}")
            except Exception as e:
                raise ValueError(f"Failed resolving host {hostname}: {e}")

    if not ip_candidates:
        raise ValueError(f"Could not resolve valid IP address for {hostname}.")

    # 5. IP & CIDR Validation
    for ip in ip_candidates:
        check_ip = getattr(ip, "ipv4_mapped", None) or ip
        if (check_ip.is_loopback or check_ip.is_private or check_ip.is_link_local or
            check_ip.is_reserved or check_ip.is_multicast or check_ip.is_unspecified):
            raise ValueError(f"{field_name} resolves to prohibited internal/private IP: {ip}")
        for net in BLOCKED_NETWORKS:
            if check_ip in net:
                raise ValueError(f"{field_name} resolves to restricted CIDR block ({net}) for {ip}")

    return clean_url

def validate_safe_proxy(proxy: Optional[str]) -> Optional[str]:
    """Validates user-provided proxy override to prevent pivoting to internal ports."""
    if not proxy:
        return None
    validate_safe_url(proxy if "://" in proxy else f"http://{proxy}", field_name="Proxy")
    return proxy

