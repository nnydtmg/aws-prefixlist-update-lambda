#!/usr/bin/env python

import boto3
import json
import urllib.request

URL = 'https://ip-ranges.amazonaws.com/ip-ranges.json'
SNS_TOPIC_ARN = 'arn:aws:sns:<region_name>:<account_id>:<topic_name>'
BASE_REGION = 'prefix_list_region'
PREFIX_NAME = 'prefix_name'

ec2 = boto3.client('ec2', region_name=BASE_REGION)
sns = boto3.client('sns', region_name=BASE_REGION)

def get_ip_ranges(URL):
    # ip-ranges.jsonを取得
    req = urllib.request.Request(URL)
    with urllib.request.urlopen(req) as res:
        ipranges = json.load(res)
    return ipranges

def get_new_ip_prefix(ipranges, region, service):
    new_prefix = []
    for key in ipranges['prefixes']:
        if key['region'] == region and key['service'] == service:
            new_prefix.append(key['ip_prefix'])
    return new_prefix

def get_current_prefix_list(name, i):
    get_prefixlist = ec2.describe_managed_prefix_lists(
        Filters=[
            {
                'Name':'prefix-list-name',
                'Values':[
                    name + str(i).zfill(3)
                ]
            },
        ]
    )
    return get_prefixlist
    
def get_current_prefix_ver(name, i):
    ver = get_current_prefix_list(name, i)['PrefixLists'][0]['Version']
    return ver
    
def get_current_entries(current_id):
    current_entries = ec2.get_managed_prefix_list_entries(
        PrefixListId = current_id
    )
    return current_entries['Entries']

def update_prefix_entries(prefixlist_id, add_entries_list, del_entries_list, ver):
    update_entries = ec2.modify_managed_prefix_list(
        PrefixListId = prefixlist_id,
        AddEntries = add_entries_list,
        RemoveEntries = del_entries_list,
        CurrentVersion = ver
    )

def lambda_handler(event, context):
    # 変数定義
    current_entries_list = []
    current_entries_ip_list = []
    del_entries_ip_list = []
    add_entries_ip_list = []
    add_entry_dist = {}
    add_entries_list = []
    del_entry_dist = {}
    del_entries_list = []
    messages = []
    
    # ip-range情報取得
    ipranges = get_ip_ranges(URL)
    
    # 必要なprefixを抽出
    ips_apne1_amazon = get_new_ip_prefix(ipranges, 'ap-northeast-1', 'AMAZON')
    ips_global_amazon = get_new_ip_prefix(ipranges, 'GLOBAL', 'AMAZON')
    ips_uset1_amazon = get_new_ip_prefix(ipranges, 'us-east-1', 'AMAZON')
    ips_uswt2_amazon = get_new_ip_prefix(ipranges, 'us-west-2', 'AMAZON')
    ips_uswt2_s3 = get_new_ip_prefix(ipranges, 'us-west-2', 'S3')
    
    # 既存の情報を取得
    for i in range(0, 1+(len(ips_apne1_amazon) // 100)):
        get_prefixlist = get_current_prefix_list(PREFIX_NAME, i+1)
        current_id = get_prefixlist['PrefixLists'][0]['PrefixListId']
        current_entries_list.extend(get_current_entries(current_id))
    
    # 不要項目削除
    for list_item_desc in current_entries_list:
        if 'Description' in list_item_desc:
            del list_item_desc['Description']
    # Cidrのみのリストを作成
    for list_item in current_entries_list:
        if 'Cidr' in list_item:
            current_entries_ip_list.append(list_item['Cidr'])
    # 登録済のCIDRから削除対象を抽出
    for diff_item in current_entries_ip_list:
        if diff_item not in ips_apne1_amazon:
            del_entries_ip_list.append(diff_item)
    # 新規登録対象のCIDRを抽出
    for diff_item in ips_apne1_amazon:
        if diff_item not in current_entries_ip_list:
            add_entries_ip_list.append(diff_item)
   
    # 各リストに対して更新をかける
    for j in range(0, 1+(len(ips_apne1_amazon) // 100)):
        current_entries = []
        current_entries_ips = []
        get_prefixlist = get_current_prefix_list(PREFIX_NAME, j+1)
        current_ver = get_prefixlist['PrefixLists'][0]['Version']
        current_id = get_prefixlist['PrefixLists'][0]['PrefixListId']
        current_entries = get_current_entries(current_id)
        for list_item in current_entries:
            if 'Cidr' in list_item:
                current_entries_ips.append(list_item['Cidr'])
        for del_item in del_entries_ip_list:
            if del_item in current_entries_ips:
                del_entry_dist = {
                    "Cidr":del_item
                }
                del_entries_list.append(del_entry_dist)
        for add_item in add_entries_ip_list:
            if add_item not in current_entries_ips and len(current_entries_ips) - len(del_entries_list) + len(add_entries_list) < 100:
                add_entry_dist = {
                    "Cidr":add_item,
                    "Description":"ips_apne1_amazon"
                }
                add_entries_list.append(add_entry_dist)
       
        if len(add_entries_list) > 0 or len(del_entries_list) > 0: 
            try:
                update_prefix_entries(current_id, add_entries_list, del_entries_list, current_ver)
                messages.append('<<<' + PREFIX_NAME + str(j+1).zfill(3) + ' is updated.>>>')
                messages.append('<<<add_entries_list>>>')
                messages.append(len(add_entries_list))
                messages.append(add_entries_list)
                messages.append('<<<del_entries_list>>>')
                messages.append(len(del_entries_list))
                messages.append(del_entries_list)
            except:
                print('<<<' + PREFIX_NAME + str(j+1).zfill(3) + ' is NOT updated.>>>')

    # SNS送信
    response = sns.publish(
        TopicArn = SNS_TOPIC_ARN,
        Message = '\n'.join(map(str,messages)),
        Subject = 'ip-rangesが更新されました'
    )
