#!/bin/bash
set -e

# Update system
yum update -y

# Install Docker
amazon-linux-extras install docker -y
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose

# Create app directory
mkdir -p /home/ec2-user/donkey
chown ec2-user:ec2-user /home/ec2-user/donkey

# Configure Docker to start on boot
systemctl enable docker

# Log completion
echo "User data script completed at $(date)" >> /var/log/user-data.log
