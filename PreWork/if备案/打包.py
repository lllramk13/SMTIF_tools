import openpyxl,os, sys,re,shutil
from collections import defaultdict
from pathlib import Path
import struct

def 导入扇区文件(打包文件夹, item_path, item, 扇区):
    "将扇区文件夹下的bin文件按顺序导入到拼接文件中"
    try:
        # 构建路径
        扇区文件夹路径 = os.path.join(item_path, 扇区)
        导入地址 = int(扇区, 16)
        输出文件路径 = os.path.join(打包文件夹, f"{item}.bin")
        
        # 收集并排序bin文件
        bin文件列表 = []
        for 文件名 in os.listdir(扇区文件夹路径):
            if 文件名.endswith('.bin') and not 文件名.startswith('.'):
                try:
                    文件基名 = os.path.splitext(文件名)[0]
                    文件数值 = int(文件基名, 16)
                    bin文件列表.append((文件数值, 文件名))
                except ValueError:
                    print(f"跳过非16进制文件名的文件: {文件名}")
                    continue
        #if not bin文件列表:
        #    print(f"扇区 {扇区} 中没有找到bin文件")
        #    return
        # 按16进制数值排序
        bin文件列表.sort(key=lambda x: x[0])
        # 处理文件拼接
        with open(输出文件路径, 'rb+') as 输出文件:
            当前偏移 = 0
            for 文件数值, 文件名 in bin文件列表:
                文件路径 = os.path.join(扇区文件夹路径, 文件名)    
                # 读取文件
                with open(文件路径, 'rb') as 输入文件:
                    文件数据 = 输入文件.read()
                数据长度 = len(文件数据)
                填充字节数 = (4 - (数据长度 % 4)) % 4
                完整数据 = 文件数据 + bytes([0x00] * 填充字节数)
                # 计算实际写入地址
                写入地址 = 导入地址 + 当前偏移
                输出文件.seek(写入地址)
                # 写入文件
                输出文件.write(完整数据)
                当前偏移 += len(完整数据)
                if  item=='F0017':
                    print('F0017',文件路径,数据长度,写入地址)
                
        最终地址=导入地址 + 当前偏移
        return  最终地址
            
    except Exception as e:
        print(f"处理扇区 {扇区} 时出错: {e}")
        import traceback
        traceback.print_exc()


def 读取EXCEL(地址列,原文列,译文列,excel文件,工作表名称=None):
    """从Excel文件中读取指针、原文和译文"""
    指针列表 = []
    原文列表 = []
    译文列表 = []
    # 打开Excel文件
    工作簿 = openpyxl.load_workbook(excel文件)
    # 如果未指定工作表名称，则使用活动工作表
    if 工作表名称 is None:
        工作表 = 工作簿.active
    else:
        工作表 = 工作簿[工作表名称]  # 获取指定名称的工作表
    # 遍历每一行，获取第一列和第三列的内容
    for row in 工作表.iter_rows():
        指针列表.append(row[地址列].value)
        原文列表.append(row[原文列].value)
        原文 = row[原文列].value if len(row) > 原文列 else None
        译文 = row[译文列].value if len(row) > 译文列 else None
        最终文本 = 译文 or 原文 or ""  # 使用or的短路特性
        译文列表.append(最终文本)
    工作簿.close()
    return 指针列表,原文列表,译文列表

def 更新码表(旧码表, 译文列表):
    空码值 = []
    for 码值, 字符 in 旧码表.items():
        if  字符 == '' and 码值 != 'EMPTY_LINE':空码值.append(码值)
    if not 空码值:
        print("警告：旧码表中没有空码值可供使用！")
        return 旧码表
    i=0
    for 文本 in 译文列表:
        if  文本 is None:
            pass
            #print(i+1,文本,译文列表[i])
        else:
            for 文字 in 文本:
                if  文字 not in 旧码表.values() and 文字 != '\n':  # 如果译文没有在旧码表中出
                    if  空码值:  # 如果仍然有空码值可用
                        空码值_item = 空码值.pop(0)  # 取出一个空的码值
                        旧码表[空码值_item] =文字  # 更新该码值与新字符的关联
                    else:
                        print("没有足够的空码值来存储新的译文：", 文本)
                        break  # 如果没有空码值可以分配给新字符，则退出
        i+=1
    return 旧码表


# 保存更新后的码表到文件 
def 保存码表(file_path, code_table):
    with open(file_path, "w", encoding="utf-16le") as file:
        file.write("\ufeff")  # 写入BOM
        for code, char in code_table.items():
            if char == '':file.write(f"{code}=\n")  # 如果字符是空字符串，表示是空行
            elif char is None:file.write(f"\n")
            else:file.write(f"{code}={char}\n")

def 一键更新码表(excel文件):
    译文列表=读取所有sheet(excel文件,原文列,译文列)
    旧码表=读取码表(导入码表文件)
    新码表=更新码表(旧码表, 译文列表)
    保存码表(导入码表文件,新码表)

def 读取所有sheet(excel文件,原文列,译文列):
    译文列表 = []
    # 打开Excel文件
    工作簿 = openpyxl.load_workbook(excel文件)
    # 遍历所有工作表
    for 工作表名称 in 工作簿.sheetnames:
        工作表 = 工作簿[工作表名称]
        for row in 工作表.iter_rows(values_only=True):
            # 使用字典或更安全的方式访问数据
            原文 = row[原文列] if len(row) > 原文列 else None
            译文 = row[译文列] if len(row) > 译文列 else None
            最终文本 = 译文 or 原文 or ""  # 使用or的短路特性
            译文列表.append(最终文本)
    工作簿.close()
    return 译文列表

def 读取码表(file_path):
    code_table = {}
    with open(file_path, "r", encoding="utf-16le") as file:
        line_number = 0 
        for line in file:
            # 去掉行末的换行符
            if line.startswith('\ufeff'):line = line[1:] 
            if '=' in line:
                code, char = line.split('=', 1)
                code_table[code.strip()] = char.rstrip('\n') 
            else:
                code_table[f"EMPTY_LINE_{line_number}"] = None  # 使用行号标记空行
            line_number+=1
    return code_table

def 读取字节(N,ROM):
     缓存字节=''
     while     N>0:
               读取字节=format(ROM.read(1)[0], '02x').upper()
               缓存字节+=读取字节
               N-=1
     读取字节=缓存字节
     return 读取字节

def 读取EXCEL(文件列,数据列,原文列,译文列,偏移地址列,excel文件,工作表名称='全文本'):
    """从Excel文件中读取指针、原文和译文"""
    文件名列表=[]
    指针列表 = []
    原文列表 = []
    译文列表 = []
    数据列表 = []
    偏移地址列表=[]
    # 打开Excel文件
    工作簿 = openpyxl.load_workbook(excel文件)
    # 如果未指定工作表名称，则使用活动工作表
    if 工作表名称 is None:
        工作表 = 工作簿.active
    else:
        工作表 = 工作簿[工作表名称]  # 获取指定名称的工作表
    # 遍历每一行，获取第一列和第三列的内容
    for row in 工作表.iter_rows():
        文件名列表.append(row[文件列].value)
        偏移地址列表.append(row[偏移地址列].value)
        数据列表.append(row[数据列].value)
        原文列表.append(row[原文列].value)
        原文 = row[原文列].value if len(row) > 原文列 else None
        译文 = row[译文列].value if len(row) > 译文列 else None
        最终文本 = 译文 or 原文 or ""  # 使用or的短路特性
        译文列表.append(最终文本)
    工作簿.close()
    return 文件名列表,数据列表,原文列表,译文列表,偏移地址列表

def 还原控制符(译文列表):
    for i in range(len(译文列表)):
        if  译文列表[i] is not None:
            译文列表[i] = 译文列表[i].replace('▽\n', '{01FF}'  )
            译文列表[i] = 译文列表[i].replace('▽', '{01FF}'  )
            译文列表[i] = 译文列表[i].replace('※※※※※※※\n', '{02FF}')
            译文列表[i] = 译文列表[i].replace('※※※※※※※', '{02FF}')
            译文列表[i] = 译文列表[i].replace('\n'            , '{03FF}')
            译文列表[i] = 译文列表[i].replace('{主角}', '{04FF}') 
            译文列表[i] = 译文列表[i].replace('{队友}', '{05FF}') 
            译文列表[i] = 译文列表[i].replace('{名字1}', '{18FF}') 
            译文列表[i] = 译文列表[i].replace('{名字4}', '{19FF}')
            译文列表[i] = 译文列表[i].replace('{道具}', '{1BFF}')
            译文列表[i] = 译文列表[i].replace('{种族1}', '{67FF}')
            译文列表[i] = 译文列表[i].replace('{种族2}', '{68FF}')
            译文列表[i] = 译文列表[i].replace('{主角等人}', '{6FFF}')
            译文列表[i] = 译文列表[i].replace('{数值0}', '{71FF}')
            译文列表[i] = 译文列表[i].replace('{数值1}', '{76FF}')
            译文列表[i] = 译文列表[i].replace('{名字3}', '{77FF}')
            译文列表[i] = 译文列表[i].replace('{恶魔1}', '{7AFF}')
            译文列表[i] = 译文列表[i].replace('{魔法}', '{7BFF}')
            译文列表[i] = 译文列表[i].replace('/', '{7CFF}')
            译文列表[i] = 译文列表[i].replace('{名字2}', '{7DFF}')
            译文列表[i] = 译文列表[i].replace('{恶魔2}', '{7FFF}')
            译文列表[i] = 译文列表[i].replace('{种族3}', '{78FF}')
            译文列表[i] = 译文列表[i].replace('{仲魔}', '{70FF}')
            译文列表[i] = 译文列表[i].replace('{数量}', '{88FF}')
            译文列表[i] = 译文列表[i].replace('{大停顿}', '{92FF}')
            译文列表[i] = 译文列表[i].replace('　', '{FEFF}')
        else:
            pass
    return 译文列表

def 文本转数据(译文列表,码表字典):
    总十六进制=''
    新偏移列表=[]
    控制符=''
    保留数据 = False
    反向字典 = {字符: 码值 for 码值, 字符 in 码表字典.items()}
    for 文本 in 译文列表:
        计数=0
        十六进制 =''
        偏移=len(总十六进制)//2
        新偏移列表.append(偏移)
        if not 文本:  # 检查文本是否为空或为None
            continue
        for 文字 in 文本:
            if   文字 == '{':
                 保留数据 = True
                 continue
            elif 文字 == '}':
                保留数据 = False
                十六进制+=控制符
                if len(控制符) % 2 != 0:
                    print('数据非双数',控制符)
                控制符=''
                continue
            if  保留数据 == True:
                控制符   += 文字
                测试=int(文字,16)
            else:
                if 文字 in 反向字典:
                    十六进制 += 反向字典[文字]
                    测试=int(反向字典[文字],16)
                    计数+=1
                else:
                    十六进制 +='0000'
        十六进制+='FFFF'
        总十六进制+=十六进制
    译文数据 = bytes.fromhex(总十六进制)
    return 译文数据,新偏移列表

def pad_to_multiple_of_4(data):
    """
    将字节数据填充到4的倍数长度
    参数:
    data: 字节数据 (bytes)
    返回:
    填充后的字节数据
    """
    remainder = len(data) % 4
    if remainder == 0:
        return data
    else:
        # 计算需要填充的字节数
        padding_length = 4 - remainder
        # 使用 b'\x00' 进行填充
        return data + b'\x00' * padding_length

def 排序并去重(地址列表, 原文列表, 译文列表):
    """按地址排序并去除重复项"""
    # 创建包含所有数据的元组列表
    数据组合 = list(zip(地址列表, 原文列表, 译文列表))
    # 过滤掉地址为None的项
    有效数据 = [(addr, orig, trans) for addr, orig, trans in 数据组合 if addr is not None]
    # 按地址排序
    排序数据 = sorted(有效数据, key=lambda x: x[0])
    # 去重（保留第一个出现的）
    去重数据 = []
    已见地址 = set()
    for addr, orig, trans in 排序数据:
        if addr not in 已见地址:
            去重数据.append((addr, orig, trans))
            已见地址.add(addr)
    # 解包回各自的列表
    排序地址, 排序原文, 排序译文 = zip(*去重数据) if 去重数据 else ([], [], [])
    return list(排序地址), list(排序原文), list(排序译文)

class LZ77Compressor:
    """LZ77压缩器类，直接处理字节数据"""
    
    def __init__(self):
        self.output = b''
        self.encoding_ptr = 0
        self.lz_seeker = 1
    
    def encode_literal(self, data, encoding_ptr, lz_seeker):
        """编码字面量数据（未压缩的原始数据）"""
        literal_output = b''
        # 分段处理字面量数据，每段最多0x80字节
        for i in range(encoding_ptr, lz_seeker, 0x80):
            # 计算当前段的长度（不超过0x80字节）
            entry_len = min(0x80, lz_seeker - i)
            # 写入长度字节（长度-1，因为0表示1字节，0x7F表示0x80字节）
            literal_output += (entry_len - 1).to_bytes(1, 'big')
            # 写入原始数据
            literal_output += data[i:i + entry_len]
        return literal_output
    
    def lz_match_getter(self, data, lz_seeker, file_size):
        """查找最长匹配的LZ77模式"""
        entry_len = 3  # 最小匹配长度为3字节
        lookback = -1  # 回溯偏移量（负数表示向前查找）
        match = None   # 存储找到的最佳匹配
        
        # 在回溯窗口内查找最长匹配
        while lookback >= -0x100 and entry_len <= 0x82:  # 回溯最多0x100字节，匹配最长0x82字节
            # 检查边界条件
            if lz_seeker + lookback < 0 or lz_seeker + entry_len > file_size:
                break
            
            # 获取当前位置的待匹配数据
            current_data = data[lz_seeker:lz_seeker + entry_len]
            # 获取回溯位置的数据
            lookback_data = data[lz_seeker + lookback:lz_seeker + lookback + entry_len]
            
            if current_data == lookback_data:
                # 找到匹配，记录并尝试更长的匹配
                match = (entry_len, lookback)
                entry_len += 1
            else:
                # 未找到匹配，尝试更远的回溯位置
                lookback -= 1
        
        return match
    
    def compress(self, input_data):
        """压缩输入的字节数据"""
        file_size = len(input_data)
        encoding_ptr = 0
        lz_seeker = 1
        output = b''
        
        # 主压缩循环
        while encoding_ptr < file_size:
            # 如果搜索指针到达文件末尾，处理剩余字面量数据
            if lz_seeker >= file_size:
                lz_seeker = file_size
                output += self.encode_literal(input_data, encoding_ptr, lz_seeker)
                break
            
            # 查找匹配模式
            match = self.lz_match_getter(input_data, lz_seeker, file_size)
            if match is None:
                # 未找到匹配，继续向前搜索
                lz_seeker += 1
                continue
            
            # 处理匹配前的字面量数据
            if (lz_seeker - encoding_ptr) > 0:
                output += self.encode_literal(input_data, encoding_ptr, lz_seeker)
            
            # 处理找到的匹配
            entry_len, lookback = match
            # 写入压缩标记（长度+0x7D，范围0x80-0xFF）
            output += (entry_len + 0x7D).to_bytes(1, 'big')
            # 写入回溯距离（取反，因为lookback是负数）
            output += (~lookback).to_bytes(1, 'big')
            
            # 更新指针位置
            lz_seeker += entry_len
            encoding_ptr = lz_seeker
        
        # 添加LZ77文件头
        compressed_data = (
            b'\x01\x02\x00\x00' +  # 魔数标记
            (len(output) + 12).to_bytes(4, 'little') +  # 压缩后数据总长度（含文件头）
            file_size.to_bytes(4, 'little') +  # 原始文件大小
            output  # 压缩数据
        )
        
        return compressed_data

# 使用示例
def compress_data(input_bytes):
    """压缩字节数据的便捷函数"""
    compressor = LZ77Compressor()
    return compressor.compress(input_bytes)

def 查找文件路径(root_dir, target_file):
    """
    使用pathlib搜索文件
    """
    root_path = Path(root_dir)
    for file_path in root_path.rglob(target_file):
        return str(file_path)
    print(root_dir, target_file)
    return None














# 获取文件所在的目录
if getattr(sys, 'frozen', False):
    基础目录 = os.path.dirname(sys.executable)
else:
    基础目录 = os.path.dirname(os.path.abspath(__file__))

文件列=0
压缩地址列=1
偏移地址列=2
原文列=3
译文列=5
excel文件 = os.path.join(基础目录, "翻译.xlsx")
导入码表文件=os.path.join(基础目录, '导入码表.tbl')

# 复制目录
解包文件夹=os.path.join(基础目录, 'unpack_D')
打包文件夹=os.path.join(基础目录, 'pack_D')
# 先检查是否存在且是目录
if os.path.exists(打包文件夹):
    # 如果是文件则删除文件
    if os.path.isfile(打包文件夹):
        os.remove(打包文件夹)
    # 如果是目录则删除目录
    elif os.path.isdir(打包文件夹):
        shutil.rmtree(打包文件夹)
shutil.copytree(解包文件夹, 打包文件夹)


一键更新码表(excel文件)
print('码表生成完毕')

文件名列表,压缩地址列表,原文列表,译文列表,偏移地址列表=读取EXCEL(文件列,压缩地址列,原文列,译文列,偏移地址列,excel文件,工作表名称='全文本')
码表字典=读取码表(导入码表文件)
译文列表=还原控制符(译文列表)

# 1. 按文件名分组，保存该文件对应的所有数据（保持原始顺序）
file_compressed_data = defaultdict(list)
for i in range(len(文件名列表)):
    filename = 文件名列表[i]
    compressed_addr = 压缩地址列表[i]
    # 使用(文件名, 压缩地址)作为唯一键
    key = (filename, compressed_addr)
    file_compressed_data[key].append({
        '原文': 原文列表[i],
        '译文': 译文列表[i],
        '偏移地址': 偏移地址列表[i]
    })

# 2. 遍历每个文件+压缩地址组合
for (filename, compressed_addr), items in file_compressed_data.items():
    # 提取当前组的所有数据
    原文列表_当前 = [item['原文'] for item in items]
    译文列表_当前 = [item['译文'] for item in items]
    偏移地址列表_当前 = [item['偏移地址'] for item in items]
    # 对当前文件的数据进行排序
    排序偏移,排序原文, 排序译文 = 排序并去重(偏移地址列表_当前, 原文列表_当前, 译文列表_当前)
    译文数据,新偏移列表_当前=文本转数据(排序译文,码表字典)
    总偏移=''
    for i, 当前偏移地址 in enumerate(偏移地址列表_当前):
        索引位置 = 排序偏移.index(当前偏移地址)
        对应偏移 = hex(新偏移列表_当前[索引位置]+len(偏移地址列表_当前)*4)[2:].zfill(8)
        对应偏移 = 对应偏移[6:8]+对应偏移[4:6]+对应偏移[2:4]+对应偏移[0:2]
        总偏移+=对应偏移
    偏移数据=bytes.fromhex(总偏移)
    偏移译文数据=偏移数据+译文数据

    压缩文件名=compressed_addr+'.bin'
    检索路径= os.path.join(打包文件夹, filename)
    output_path =查找文件路径(检索路径,压缩文件名)

    with open(output_path, 'rb+') as ROM:
        压缩类型及编号=读取字节(4,ROM)
        压缩类型=压缩类型及编号[0:2]
        if   压缩类型=='02':
            print('压缩类型=02',filename, compressed_addr)
        编号=压缩类型及编号[4:8]
        原压缩长度=读取字节(4,ROM)
        原压缩长度=int(原压缩长度[6:8]+原压缩长度[4:6]+原压缩长度[2:4]+原压缩长度[0:2],16)
        新压缩数据 = compress_data(偏移译文数据)
        if  len(新压缩数据)>len(偏移译文数据)+8:
            新压缩数据=b'\x01\x00'+bytes.fromhex(编号)+(len(偏移译文数据)+8).to_bytes(4, 'little')+偏移译文数据
        else:
            新压缩数据=b'\x01\x02'+bytes.fromhex(编号)+新压缩数据[4:]
        ROM.seek(0)
        ROM.truncate()  # 清空文件内容
        ROM.write(新压缩数据)

# 3.拼接数据
    "遍历根目录下的所有直接子文件夹"
for item in os.listdir(打包文件夹):
    item_path = os.path.join(打包文件夹, item)# item:F0016
    if os.path.isdir(item_path):
        输出文件路径 = os.path.join(打包文件夹, f"{item}.bin")
        with open(输出文件路径, 'rb') as 输出文件:
            输出文件数据=输出文件.read()
            输出文件总长度=len(输出文件数据)
        for 扇区 in os.listdir(item_path):
            最终地址=0
            if  最终地址> int(扇区, 16):
                print(item,扇区,'导入异常,新长度>原扇区长度')
            扇区路径 = os.path.join(item_path, 扇区)
            if os.path.isdir(扇区路径):
                try:
                    # 验证是否为16进制文件夹名
                    int(扇区, 16)
                    最终地址=导入扇区文件(打包文件夹, item_path, item, 扇区)
                except ValueError:
                    print(f"跳过非16进制文件夹: {扇区}")
        补充长度=输出文件总长度-最终地址
        with open(输出文件路径, 'rb+') as 输出文件:
            print(输出文件,最终地址)
            输出文件.seek(最终地址)
            输出文件.write(补充长度*b'\x00')
