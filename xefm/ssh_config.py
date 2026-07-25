"""
SSH Configuration Parser

Parses SSH configuration files to discover remote servers.
Supports Host entries, Include directives, and wildcard exclusion.
"""

import os
from pathlib import Path
from xefm.log_manager import getLogger


class SSHConfigParser:
    """
    Parses SSH configuration files to discover remote servers.
    
    Supports:
    - Host entries with connection parameters
    - Include directives for additional config files
    - Wildcard exclusion (Host * entries are ignored)
    """
    
    def __init__(self, config_path: str = "~/.ssh/config"):
        """
        Initialize parser.
        
        Args:
            config_path: Path to SSH config file (default: ~/.ssh/config)
        """
        self.config_path = os.path.expanduser(config_path)
        self.logger = getLogger("SSHCfg")
    
    def parse(self) -> dict:
        """
        Parse SSH config file.
        
        Returns:
            Dictionary mapping hostname to configuration dict
            {
                'hostname': {
                    'HostName': 'actual.host.com',
                    'User': 'username',
                    'Port': 22,
                    'IdentityFile': '/path/to/key',
                    ...
                }
            }
            
            Returns empty dict if config file doesn't exist or parsing fails.
        """
        hosts = {}
        
        # Handle missing config file gracefully
        if not os.path.exists(self.config_path):
            self.logger.info(f"SSH config file not found: {self.config_path}")
            return hosts
        
        try:
            self._parse_file(self.config_path, hosts)
        except Exception as e:
            self.logger.warning(f"Failed to parse SSH config: {e}")
            return {}
        
        return hosts
    
    def _parse_file(self, file_path: str, hosts: dict):
        """
        Parse a single config file.
        
        Args:
            file_path: Path to config file
            hosts: Dictionary to populate with host entries
        """
        try:
            with open(file_path, 'r') as f:
                current_host = None
                current_config = {}
                
                for line_num, line in enumerate(f, 1):
                    # Strip comments and whitespace
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    # Split into key and value
                    parts = line.split(None, 1)
                    if len(parts) < 1:
                        continue
                    
                    key = parts[0]
                    value = parts[1] if len(parts) > 1 else ''
                    
                    # Handle Host directive
                    if key.lower() == 'host':
                        # Save previous host if any
                        if current_host and not self._is_wildcard_host(current_host):
                            hosts[current_host] = current_config
                        
                        # Start new host
                        current_host = value
                        current_config = {}
                    
                    # Handle Include directive
                    elif key.lower() == 'include':
                        include_path = os.path.expanduser(value)
                        # Handle relative paths
                        if not os.path.isabs(include_path):
                            config_dir = os.path.dirname(file_path)
                            include_path = os.path.join(config_dir, include_path)
                        
                        # Recursively parse included file
                        if os.path.exists(include_path):
                            self._parse_file(include_path, hosts)
                        else:
                            self.logger.warning(f"Include file not found: {include_path}")
                    
                    # Handle configuration options
                    elif current_host:
                        # Store configuration option for current host
                        current_config[key] = value
                
                # Save last host if any
                if current_host and not self._is_wildcard_host(current_host):
                    hosts[current_host] = current_config
        
        except Exception as e:
            self.logger.warning(f"Error parsing {file_path}: {e}")
            raise
    
    def _is_wildcard_host(self, host_pattern: str) -> bool:
        """
        Check if host pattern is a wildcard.
        
        Args:
            host_pattern: Host pattern from config
            
        Returns:
            True if pattern contains wildcards (* or ?)
        """
        return '*' in host_pattern or '?' in host_pattern
