---
description: Ubuntu terminal operator — run shell commands, manage files, install packages, and administer the system
argument-hint: "<shell command or system task>"
allowed-tools: Bash, Read, Write
---

# /terminal — Ubuntu Terminal Operator

**Purpose:** Execute any task a user would do in an Ubuntu terminal — SSH into remote servers, manage packages, install dependencies, run system commands, and perform administrative tasks.

**Use this skill when:**
- User asks to SSH into a server/VPS
- Need to install system packages (`apt`, `snap`, `npm`, `pip`, etc.)
- Need to run system administration tasks
- Need to check server status, logs, or processes
- Need to update dependencies or upgrade system packages
- Need to perform any interactive terminal workflow

---

## Capabilities

### SSH & Remote Access
- SSH into remote servers with password or key authentication
- Execute remote commands via SSH
- Transfer files via SCP/SFTP
- Check remote server status (Docker, services, disk, memory)
- Deploy applications to remote servers

### Package Management
```bash
# APT (Debian/Ubuntu)
sudo apt update && sudo apt upgrade -y
sudo apt install <package>
sudo apt remove <package>
sudo apt autoremove

# Snap
sudo snap install <package>
sudo snap refresh

# NPM (global)
npm install -g <package>
npm update -g

# Pip (Python)
pip install <package>
pip freeze
```

### System Administration
```bash
# Process management
ps aux | grep <process>
top / htop
kill <pid>
systemctl status <service>
systemctl restart <service>

# Disk & memory
df -h
du -sh /path
free -h

# Network
netstat -tulpn
ss -tulpn
curl -I https://example.com
ping -c 4 host

# Logs
journalctl -u <service> -f
tail -f /var/log/syslog
dmesg | tail
```

### Docker & Containers
```bash
docker ps -a
docker images
docker logs <container>
docker exec -it <container> bash
docker-compose up -d
docker-compose down
docker-compose logs -f
```

### Git Operations
```bash
git status
git pull / git push
git checkout -b <branch>
git merge <branch>
git rebase
```

---

## Usage

### Basic Terminal Command
```
/terminal <command>
```

### SSH into Server
```
/terminal ssh into server and check docker containers
/terminal ssh to server and restart the service
/terminal ssh into vps and show me the last 50 lines of the logs
```

### Install Packages
```
/terminal install sshpass
/terminal install nodejs 20
/terminal install docker-compose plugin
```

### Check Server Status
```
/terminal check if nginx is running
/terminal show me disk usage on /opt
/terminal check memory and cpu usage
```

### Update Dependencies
```
/terminal update all npm packages
/terminal run apt upgrade
/terminal update all python packages
```

### Deploy & Manage
```
/terminal deploy the latest tag to production
/terminal restart all containers
/terminal run the database migrations
```

---

## Security Guidelines

1. **Credentials**: Never store passwords in files. Use environment variables or secrets.
2. **Destructive commands**: Ask before running `rm -rf`, `drop`, `delete`, `format`
3. **Production access**: Confirm before SSHing into production servers
4. **Backups**: Suggest backup before database migrations or schema changes

---

## SSH Command Templates

### Option 1: Direct SSH (Interactive Password)
```bash
ssh -o StrictHostKeyChecking=no <user>@<host> "<command>"
# You'll be prompted for the password interactively
```

### Option 2: SSH Key (Recommended for Automation)
```bash
ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no <user>@<host> "<command>"
# Requires your public key to be added to ~/.ssh/authorized_keys on the remote server
```

### Option 3: sshpass (Use with Caution)
```bash
sshpass -p '<password>' ssh -o StrictHostKeyChecking=no <user>@<host> "<command>"
# Note: Passwords with special characters (!, $, etc.) may need escaping
# Avoid using in scripts - prefer SSH keys instead
```

---

## Security Best Practices

| Do | Don't |
|----|-------|
| Use SSH keys for automation | Store passwords in plain text files |
| Use environment variables for secrets | Commit credentials to git |
| Escalate with sudo when needed | Run as root unnecessarily |
| Verify host fingerprints | Blindly accept all host keys |

---

## Error Handling

If a command fails:
1. Show the error output clearly
2. Suggest common fixes (permissions, missing package, network)
3. Offer to retry with adjusted parameters
4. For SSH failures, try alternative auth method (password ↔ key)

---

## Notes

- This skill uses the `Bash` tool for all operations
- For complex multi-step workflows, chain commands with `&&` or `;`
- Long-running commands should use `run_in_background: true`
- Always quote paths with spaces
- Use absolute paths when possible for reliability

---

**Evolution Log:**
- [2026-03-27] Created — Ubuntu terminal operator for SSH, package management, and system administration
- [2026-03-27] Removed hardcoded credentials — use environment variables or project memory instead
