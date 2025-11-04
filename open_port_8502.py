#!/usr/bin/env python3
"""
Open port 8502 in AWS Security Group
"""

import boto3
import requests

# Get instance metadata
TOKEN = requests.put(
    'http://169.254.169.254/latest/api/token',
    headers={'X-aws-ec2-metadata-token-ttl-seconds': '21600'},
    timeout=2
).text

headers = {'X-aws-ec2-metadata-token': TOKEN}

instance_id = requests.get(
    'http://169.254.169.254/latest/meta-data/instance-id',
    headers=headers,
    timeout=2
).text

region = requests.get(
    'http://169.254.169.254/latest/meta-data/placement/region',
    headers=headers,
    timeout=2
).text

print(f"Instance ID: {instance_id}")
print(f"Region: {region}")

# Get EC2 client
ec2 = boto3.client('ec2', region_name=region)

# Get instance details
response = ec2.describe_instances(InstanceIds=[instance_id])
security_groups = response['Reservations'][0]['Instances'][0]['SecurityGroups']

print(f"\nSecurity Groups:")
for sg in security_groups:
    sg_id = sg['GroupId']
    sg_name = sg['GroupName']
    print(f"  {sg_name}: {sg_id}")

    # Check if port 8502 is already open
    sg_details = ec2.describe_security_groups(GroupIds=[sg_id])

    port_open = False
    for rule in sg_details['SecurityGroups'][0]['IpPermissions']:
        if rule.get('FromPort') == 8502 and rule.get('ToPort') == 8502:
            port_open = True
            print(f"    ✅ Port 8502 is already open!")
            break

    if not port_open:
        print(f"    ⚠️  Port 8502 is NOT open. Opening now...")

        try:
            ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 8502,
                        'ToPort': 8502,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'Streamlit Dev Environment'}]
                    }
                ]
            )
            print(f"    ✅ Port 8502 opened successfully!")
        except Exception as e:
            if 'InvalidPermission.Duplicate' in str(e):
                print(f"    ✅ Port 8502 is already open (duplicate rule)")
            else:
                print(f"    ❌ Error: {e}")
