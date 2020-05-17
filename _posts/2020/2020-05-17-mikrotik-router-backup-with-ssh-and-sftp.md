---
layout: post
title:  "Mirkotik router backup with SSH and SFTP"
categories: tech
tags: [mikrotik]
comments: True
---

Everybody knows how important it is to backup. I use Mikrotik Routers in my home network and have quite complex configuration
which I would not want to write again from scratch. Prior to this day I have used scheduled script on Mikrotik to create backups 
locally, transferring it out of router itself into another location is great way to increase backup durability.

<!-- readmore -->

## Setup

To be able to use backup script you should have ssh key pair as ssh is used as secure protocol to connect
to router. 
Upload your public key to Mikrotik via `Files` menu and execute:
```bash
/user ssh-keys import user=admin public-key-file=id_rsa.pub
```

**Note:** To generate new ssh key pair you can use `ssh-keygen`.   

**Important:** By sshing to router with this key you will have admin privliedges. I was not sure if there is poossiblity to lower permissions 
for backup purposes. Leave me a note if that's the case.

## Script

If we have `ssh` connectivity from system that should do backup then it's time to do remote backup.

This script will:
- write log and create backup
- download backup with sftp
- remove backup from router and log end of script execution

```bash
#!/bin/bash -e
USER=admin
SERVER=$1
URI="$USER@$SERVER"
DIR=/Storage/Backup/mikrotik

NAME=`echo "$(date '+%Y%m%d-%s').backup"`

ssh $URI 'log info message="Backup to storage started";'
ssh $URI "system backup save name=$NAME;"
sftp $URI:$NAME
mv $NAME $DIR/$SERVER-$NAME
# Sleep needed as file might not be available for deletion right away
sleep 3;
ssh $URI "file remove \"$NAME\""
ssh $URI 'log info message="Backup to storage completed"'
```

$1 is variable which is passed as arguemnt to script. Ex:
```bash
/backup.sh 192.168.88.1
```
If you have more than one device then it's easy to backup all of them.

3h4x