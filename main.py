import json
import os
import subprocess
from time import sleep
import paramiko
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.cvm.v20170312 import cvm_client, models as cvm_models  # pip install tencentcloud-sdk-python-cvm
from tencentcloud.vpc.v20170312 import vpc_client, models as vpc_models  # pip install tencentcloud-sdk-python-vpc


def get_cred(credfile):
    with open(credfile, 'r', encoding='utf-8-sig') as file:
        credentials = json.load(file)
    secret_id = credentials.get('SecretId')
    secret_key = credentials.get('SecretKey')
    password = credentials.get('Password')
    cred = credential.Credential(secret_id, secret_key)
    return cred, password


def get_clientProfile(type):
    httpProfile = HttpProfile()
    httpProfile.endpoint = type + ".tencentcloudapi.com"
    clientProfile = ClientProfile(httpProfile=httpProfile)
    return clientProfile


# 模块加载器
def module_loader(module):
    module_config_file = 'hello_shell.json'
    try:
        with open(module_config_file, 'r', encoding='utf-8-sig') as file:
            templates = json.load(file)
            if module in templates:
                module_info = templates[module]
                description = module_info.get('description', 'N/A')
                price = module_info.get('Price', 'N/A')
                region = module_info.get('region', 'N/A')
                params = module_info.get('params', {})
                print(f"已载入: {description}\n资费信息: {price}")
                return region, params
            else:
                print(f"无效配置 未找到对应模块'{module}' ")
    except FileNotFoundError:
        print(f"配置文件 '{module_config_file}' 的坐标呢？")
    except json.JSONDecodeError:
        print(f"'{module_config_file}'是什么破玩意,理解不了!说了让你用json 用json!!! ")


# 安全组查询
def check_security_group(cred, clientProfile, region):
    try:
        client = vpc_client.VpcClient(cred, region, clientProfile)

        req = vpc_models.DescribeSecurityGroupsRequest()
        params = {}
        req.from_json_string(json.dumps(params))
        resp = client.DescribeSecurityGroups(req)
        resp_json = json.loads(resp.to_json_string())

        security_groups = resp_json.get("SecurityGroupSet", [])
        total_count = len(security_groups)
        print(f"在该地区查询到 {total_count} 个安全组, id为", end=' ')
        for group in security_groups:
            print(group["SecurityGroupId"], end=' ')

        for group in security_groups:
            if "放通全部端口" in group["SecurityGroupName"]:
                return group["SecurityGroupId"]
        print("\n没有检测到全通安全组，正在创建...")
        return create_security_group(cred, clientProfile, region)


    except TencentCloudSDKException as err:
        print(f"Error occurred: {err}")
        return None


# 安全组创建
def create_security_group(cred, clientProfile, region):
    try:
        client = vpc_client.VpcClient(cred, region, clientProfile)

        req = vpc_models.CreateSecurityGroupWithPoliciesRequest()
        params = {
            "GroupName": "放通全部端口-Tencent-ARL",
            "GroupDescription": "放通全部端口-Tencent-ARL",
            "SecurityGroupPolicySet": {
                "Egress": [
                    {
                        "PolicyIndex": 0,
                        "Protocol": "ALL",
                        "Port": "ALL",
                        "Action": "ACCEPT"
                    }
                ],
                "Ingress": [
                    {
                        "Protocol": "ALL",
                        "Port": "ALL",
                        "Action": "ACCEPT"
                    }
                ]
            }
        }
        req.from_json_string(json.dumps(params))
        resp = client.CreateSecurityGroupWithPolicies(req)
        resp_json = json.loads(resp.to_json_string())
        print(f"创建安全组 {resp_json['SecurityGroup']['SecurityGroupId']} 成功")
        return resp_json["SecurityGroup"]["SecurityGroupId"]

    except TencentCloudSDKException as err:
        print(f"Error occurred: {err}")
        return None


# 查询实例
def describe_instances(cred, clientProfile, region, InstanceIds):
    try:
        client = cvm_client.CvmClient(cred, region, clientProfile)
        req = cvm_models.DescribeInstancesRequest()
        params = {
            "InstanceIds": [InstanceIds]
        }
        req.from_json_string(json.dumps(params))
        resp = client.DescribeInstances(req)
        resp_json = json.loads(resp.to_json_string())

        if resp_json.get("TotalCount", 0) > 0:
            instance_info = resp_json["InstanceSet"][0]

            if "PublicIpAddresses" in instance_info and instance_info["PublicIpAddresses"]:
                public_ip = instance_info["PublicIpAddresses"][0]
                instance_type = instance_info.get("InstanceType", "Unknown")
                instance_data = {
                    "username_at_ip": f"ubuntu@{public_ip}",
                    "region": region
                }

                print(f"ubuntu@{public_ip} 创建完成 机型 {instance_type}")
                global ip
                ip = public_ip

                try:
                    with open("running.json", "r") as file:
                        existing_data = json.load(file)
                except FileNotFoundError:
                    existing_data = {}

                existing_data[InstanceIds] = instance_data

                with open("running.json", "w") as file:
                    json.dump(existing_data, file)

                return public_ip
            else:
                print(f"等待实例 {instance_id} 初始化...")
                sleep(5)
                return describe_instances(cred, clientProfile, region, InstanceIds)
        else:
            print("未找到指定的实例")
            return None

    except TencentCloudSDKException as err:
        print(err)
        return None


# 创建实例
def create_instance(cred, clientProfile, region, params, openID, passwd):
    try:
        client = cvm_client.CvmClient(cred, region, clientProfile)
        req = cvm_models.RunInstancesRequest()

        params["SecurityGroupIds"] = [openID]
        # 如果 params["LoginSettings"]["Password"] 不存在，即为公钥登录
        if "LoginSettings" in params and "Password" in params["LoginSettings"]:
            params["LoginSettings"]["Password"] = passwd

        req.from_json_string(json.dumps(params))
        resp = client.RunInstances(req)
        resp_json = json.loads(resp.to_json_string())

        instance_id_set = resp_json.get("InstanceIdSet", [])
        if instance_id_set:
            instance_id = instance_id_set[0]
            print(f"成功创建实例 ID {instance_id}")
            return instance_id
        else:
            print("未能成功创建实例 报错信息如下")
            return None

    except TencentCloudSDKException as err:
        print(err)
        return None


# 退还实例
def terminate_instance(cred, clientProfile, InstanceIds=None):
    try:
        # 从文件读取运行中的实例信息
        with open("running.json", "r") as file:
            running_instances = json.load(file)

        if InstanceIds:
            # 退还指定的实例
            if InstanceIds in running_instances:
                instance_info = running_instances[InstanceIds]
                region = instance_info["region"]
                client = cvm_client.CvmClient(cred, region, clientProfile)

                print(f"运行中 ID：{instance_info['username_at_ip']}")

                req = cvm_models.TerminateInstancesRequest()
                params = {"InstanceIds": [InstanceIds]}
                req.from_json_string(json.dumps(params))
                resp = client.TerminateInstances(req)

                print(f"实例 {InstanceIds} 已退还")
                del running_instances[InstanceIds]
            else:
                print(f"实例 {InstanceIds} 不存在或已被退还")

        else:
            # 退还所有实例
            for InstanceId, instance_info in running_instances.items():
                region = instance_info["region"]
                client = cvm_client.CvmClient(cred, region, clientProfile)

                print(f"运行中 ID：{instance_info['username_at_ip']}")

                req = cvm_models.TerminateInstancesRequest()
                params = {"InstanceIds": [InstanceId]}
                req.from_json_string(json.dumps(params))
                resp = client.TerminateInstances(req)

                print(f"实例 {InstanceId} 已退还")
            running_instances.clear()

        with open("running.json", "w") as file:
            json.dump(running_instances, file)

    except FileNotFoundError:
        print("没有找到 'running.json' 文件")
    except json.JSONDecodeError:
        print("'running.json' 文件格式错误")
    except TencentCloudSDKException as err:
        print(err)


def start_ssh_session(username, ip):
    if ip is None:
        print("实例创建出现问题，请检查日志")
        return
    ssh_command = ["ssh", "-o", "StrictHostKeyChecking=no", f"{username}@{ip}"]
    subprocess.run(ssh_command)


def install_docker_compose(address, username, password):
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(address, 22, username, password)
    cmd = ('git clone https://gitee.com/r1ck-f/docker-setup-1.git '
           '&& cd docker-setup-1 '
           '&& chmod 777 install.sh && ./install.sh')
    stdin, stdout, stderr = ssh_client.exec_command(cmd)
    out = stdout.read().decode('utf-8')
    ssh_client.close()
    if 'docker-compose version' in out:
        return 1
    else:
        return 0


def install_arl_worker(address, port, username, password):
    # 判断是否存在ARL-Distributed文件夹
    if os.path.exists(r'./ARL-Distributed'):
        pass
    else:
        print("请将ARL-Distributed文件夹放在当前目录下")
        exit(0)
    # 判断当前系统是否为Windows
    if os.name == 'nt':
        # 判断是否存在ARL-Distributed.zip文件
        if os.path.exists(r'./ARL-Distributed.zip'):
            print("当前系统为Windows,已存在ARL-Distributed.zip文件")
            print("正在上传ARL-Distributed.zip文件到远程服务器........")
        else:
            print("当前系统为Windows,请自行打包为zip文件到当前目录下")
            exit(0)
    else:
        cmd1 = 'zip -r ARL-Distributed.zip ARL-Distributed'
        os.system(cmd1)
    local_path = r'./ARL-Distributed.zip'
    remote_path = '/root/'
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(address, port, username, password)
    # 通过SFTP上传ZIP文件到远程服务器并解压
    sftp_client = ssh_client.open_sftp()
    sftp_client.put(local_path, remote_path + 'ARL-Distributed.zip')
    sftp_client.close()
    cmd0 = 'unzip -o /root/ARL-Distributed.zip -d /root/'
    stdin, stdout, stderr = ssh_client.exec_command(cmd0)
    out = stdout.read().decode('utf-8')

    # 关闭连接
    sftp_client.close()
    ssh_client.close()


def start_arl_worker(address, port, username, password):
    # 执行命令通过docker-compose运行容器
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(address, port, username, password)
    cmd = 'cd /root/ARL-Distributed/worker && docker-compose up -d'
    stdin, stdout, stderr = ssh_client.exec_command(cmd)
    out = stdout.read().decode('utf-8')
    ssh_client.close()
    print(out)


def print_project_info():
    print("********** Tencent+ARL-worker **********")
    print("——快速创建arl-worker By 7eleven")


if __name__ == "__main__":
    print_project_info()
    ip = None
    addresses = []
    print(">0 退出")
    print(">1 创建实例&安装docker-compose(默认使用模块1)")
    print(">2 模块选择(用于反弹shell)")
    print(">3 批量上传arl-worker")
    print(">4 批量启动arl-worker")
    print(">5 退还所有实例(running.json内的实例))")

    choice = input(">>> ")

    cred, passwd = get_cred("cred")
    cvm_clientProfile = get_clientProfile("cvm")
    vpc_clientProfile = get_clientProfile("vpc")

    if choice == '0':
        exit(0)

    if choice == '1':
        # 请输入创建实例的数量
        num = input("请输入创建实例的数量：")
        if num == '':
            num = 1
        # 默认使用模块2创建一台服务器
        for i in range(int(num)):
            region, params = module_loader("module_1")
            openID = check_security_group(cred, vpc_clientProfile, region)
            instance_id = create_instance(cred, cvm_clientProfile, region, params, openID, passwd)
            address = describe_instances(cred, cvm_clientProfile, region, instance_id)
            install_docker_compose(address, 'root', passwd)
            addresses.append(address)
        print(addresses)


    elif choice == '2':
        # 自定义启动模块
        with open('hello_shell.json', 'r', encoding='utf-8-sig') as file:
            templates = json.load(file)

        print("\n可用模块：")
        for key, value in templates.items():
            print(f"{key}: {value['description']}, 资费信息: {value['Price']}")

        module_choice = input("\n请选择要使用的模块 (例如: module_3): ")
        if module_choice in templates:
            region, params = module_loader(module_choice)
            openID = check_security_group(cred, vpc_clientProfile, region)
            instance_id = create_instance(cred, cvm_clientProfile, region, params, openID, passwd)
            address = describe_instances(cred, cvm_clientProfile, region, instance_id)
            if module_choice == 'module_1':
                start_ssh_session('root', address)
            else:
                start_ssh_session('ubuntu', address)
        else:
            print("无效的模块选择")

    elif choice == '3':
        # 批量安装arl-worker
        with open("running.json", "r") as file:
            running_instances = json.load(file)
        for InstanceId, instance_info in running_instances.items():
            region = instance_info["region"]
            address = instance_info["username_at_ip"]
            addresses.append(address)
        for address in addresses:
            # 获取ip
            ip = address.split('@')[1]
            install_arl_worker(ip, 22, 'root', passwd)
        print("done")

    elif choice == '4':
        # 批量启动arl-worker
        with open("running.json", "r") as file:
            running_instances = json.load(file)
        for InstanceId, instance_info in running_instances.items():
            region = instance_info["region"]
            address = instance_info["username_at_ip"]
            addresses.append(address)
        for address in addresses:
            # 获取ip
            ip = address.split('@')[1]
            start_arl_worker(ip, 22, 'root', passwd)

    elif choice == '5':
        # 退还所有实例
        terminate_instance(cred, cvm_clientProfile)

    else:
        print("?你在选什么!")
