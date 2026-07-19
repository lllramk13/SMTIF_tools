import os
import struct
import shutil
import binascii

def 读取字节(N,ROM):
     缓存字节=''
     while     N>0:
               读取字节=format(ROM.read(1)[0], '02x').upper()
               缓存字节+=读取字节
               N-=1
     读取字节=缓存字节
     return 读取字节
def 龙门解压(解压长度,解压地址):
    with    open(文件路径, 'rb') as ROM:
            ROM.seek(解压地址)
            文件类型=读取字节(4,ROM)
            解压数据='' # 存储解压后的数据
            if 文件类型[0:4]=='0102':
               压缩长度=读取字节(4,ROM)
               压缩长度=int(压缩长度[6:8]+压缩长度[4:6]+压缩长度[2:4]+压缩长度[0:2],16)
               解压长度=读取字节(4,ROM)
               解压长度=int(解压长度[6:8]+解压长度[4:6]+解压长度[2:4]+解压长度[0:2],16)
               while   解压长度>0:
                       # 读取一字节标志符
                       标志符=int(读取字节(1,ROM),16)
                       if      标志符<0x80:
                               直读长度=标志符+1
                               直读数据=读取字节(直读长度,ROM)
                               解压数据+=直读数据
                               解压长度=解压长度-直读长度
                       else:   
                               第一字节=读取字节(1,ROM)
                               #复用数据，复用长度=N-7D，复用数据来源=存入地址-第一字节
                               复用开始位置=len(解压数据)-int(第一字节,16)*2-2
                               复用长度=标志符-0x7D
                               复用结束位置=复用开始位置+复用长度*2
                               解压长度=解压长度-复用长度
                               while   复用结束位置!=复用开始位置:
                                       解压数据+=解压数据[复用开始位置:复用开始位置+2]
                                       复用开始位置=复用开始位置+2
            elif 文件类型[0:4]=='0101':
                压缩长度=读取字节(4,ROM)
                压缩长度=int(压缩长度[6:8]+压缩长度[4:6]+压缩长度[2:4]+压缩长度[0:2],16)
                解压长度=读取字节(4,ROM)
                解压长度=int(解压长度[6:8]+解压长度[4:6]+解压长度[2:4]+解压长度[0:2],16)
                while   解压长度>0:
                        # 读取一字节标志符
                        标志符=int(读取字节(1,ROM),16)
                        if      标志符<0x80:
                                直读长度=标志符+1
                                直读数据=读取字节(直读长度,ROM)
                                解压数据+=直读数据
                                解压长度=解压长度-直读长度
                        else:   
                                第一字节=读取字节(1,ROM)
                                #复用数据，复用长度=N-7D，复用数据来源=第一字节
                                复用长度=标志符-0x7D
                                解压长度=解压长度-复用长度
                                解压数据+=第一字节*复用长度
            elif 文件类型[0:4]=='0200':
                压缩长度=读取字节(4,ROM)
                压缩长度=int(压缩长度[6:8]+压缩长度[4:6]+压缩长度[2:4]+压缩长度[0:2],16)
                未知字节=读取字节(4,ROM)
                参数1=读取字节(2,ROM)
                参数1=int(参数1[2:4]+参数1[0:2],16)
                参数2=读取字节(2,ROM)
                参数2=int(参数2[2:4]+参数2[0:2],16)
                解压长度=参数1*参数2*2
                直读数据=读取字节(解压长度,ROM)
                解压数据+=直读数据
            elif 文件类型[0:4]=='0201':
                压缩长度=读取字节(4,ROM)
                压缩长度=int(压缩长度[6:8]+压缩长度[4:6]+压缩长度[2:4]+压缩长度[0:2],16)
                未知字节=读取字节(4,ROM)
                参数1=读取字节(2,ROM)
                参数1=int(参数1[2:4]+参数1[0:2],16)
                参数2=读取字节(2,ROM)
                参数2=int(参数2[2:4]+参数2[0:2],16)
                解压长度=参数1*参数2*2
                while 解压长度>0:
                   # 读取一字节标志符
                   标志符=int(读取字节(1,ROM),16)
                   if   标志符<0x80:
                        直读长度=标志符+1
                        直读数据=读取字节(直读长度,ROM)
                        解压数据+=直读数据
                        解压长度=解压长度-直读长度
                   else:
                        第一字节=读取字节(1,ROM)
                        #复用数据，复用长度=N-7D
                        复用长度=标志符-0x7D
                        解压长度=解压长度-复用长度
                        解压数据+=第一字节*复用长度
            当前地址= ROM.tell()
            读取长度=当前地址-解压地址
            return 解压数据,读取长度

def extract_and_save(filename):
    # 创建输出目录，与输入文件同名
    with open(filename, 'rb') as f:
        data = f.read()
    offset = 0  # 当前位置
    提取文件数=0
    编号=0
    while offset < len(data):
            #print(hex(offset))
            if  (offset & 3) == 0:#如果地址是4的倍数
                #print(offset)
                header=data[offset:offset + 2]
                if  int.from_bytes(data[offset:offset+2], byteorder='little')!=0 and int.from_bytes(data[offset+2:offset+4], byteorder='little')==0:
                    编号+=1
                if  header==b'\x01\x02' or header==b'\x01\x01':
                    # 读取压缩数据长度和解压数据长度
                    # 按小端序拼接转换为整数
                    压缩长度 = int.from_bytes(data[offset+4:offset+8], byteorder='little')
                    解压长度 = int.from_bytes(data[offset+8:offset+12], byteorder='little')
                    if  压缩长度+offset<len(data):
                        # 进行解压
                        解压数据,读取长度 = 龙门解压(解压长度,offset)
                        if  解压长度==len(解压数据)//2:
                            字节数据 =bytes.fromhex(解压数据)
                            # 检查解压数据长度是否匹配
                            if  读取长度 == 压缩长度:
                                output_dir = os.path.join(目录,'unpack_D',os.path.splitext(os.path.basename(filename))[0],str(编号))
                                os.makedirs(output_dir, exist_ok=True)
                                output_file = os.path.join(output_dir,f'{hex(offset)[2:].zfill(8).upper()}.bin')
                                with open(output_file, 'wb') as out_f:
                                    out_f.write(字节数据)
                                    提取文件数+=1
                        offset += 压缩长度 
                    else:
                        offset+=4
                elif    header==b'\x01\x00':
                    # 取 offset+4 到 offset+8 的字节数据
                    byte_data = data[offset+4:offset+8]
                    # 按小端序拼接转换为整数
                    压缩长度 = int.from_bytes(byte_data, byteorder='little')
                    if  压缩长度+offset<len(data):
                        if  压缩长度>8:
                            解压数据=''
                            解压数据 += binascii.hexlify(data[offset+8:offset+压缩长度]).decode().upper()
                            字节数据 =bytes.fromhex(解压数据)
                            output_dir = os.path.join(目录,'unpack_D',os.path.splitext(os.path.basename(filename))[0],str(编号))
                            os.makedirs(output_dir, exist_ok=True)
                            output_file = os.path.join(output_dir,f'{hex(offset)[2:].zfill(8).upper()}.bin')
                            with open(output_file, 'wb') as out_f:
                                out_f.write(字节数据)
                                提取文件数+=1
                            offset+=压缩长度
                        else:
                            offset+=4
                    else:
                        offset+=4

                elif    header==b'\x02\x01'or header==b'\x02\x00':
                        压缩长度 = int.from_bytes(data[offset+4:offset+8], byteorder='little')
                        解压长度 = int.from_bytes(data[offset+12:offset+14], byteorder='little')*int.from_bytes(data[offset+14:offset+16], byteorder='little')*2
                        解压数据,读取长度 = 龙门解压(解压长度,offset)
                        字节数据 =bytes.fromhex(解压数据)
                        output_dir = os.path.join(目录,'unpack_D',os.path.splitext(os.path.basename(filename))[0],str(编号))
                        os.makedirs(output_dir, exist_ok=True)
                        output_file = os.path.join(output_dir,f'{hex(offset)[2:].zfill(8).upper()}.bin')
                        with open(output_file, 'wb') as out_f:
                            out_f.write(字节数据)
                            提取文件数+=1
                        # 检查解压数据长度是否匹配
                        if  读取长度 == 压缩长度:
                            pass
                        else:
                            print(hex(offset)+'长度异常',hex(压缩长度))
                        offset += 压缩长度
                elif    header==b'\x00\x00':
                        offset+=4
                else:
                    print(filename,header,offset)
                    offset+=4
            else:
                offset+=1
    # 如果未提取到任何文件，删除输出目录
    if 提取文件数 == 0:
        print(f"未提取到文件，已删除目录: {filename}")
    else:
        print(f"成功提取 {提取文件数} 个文件到目录: {output_dir}")


# 获取当前脚本所在的目录
目录 = os.path.dirname(os.path.abspath(__file__))
# 构造D文件夹的路径
D文件夹路径 = os.path.join(目录, 'comp_D')#,'E'
解包文件夹  = os.path.join(目录, '解压解包')#,'E'

# 检查D文件夹是否存在
if not os.path.exists(D文件夹路径):
    print("D文件夹未找到！")
else:
    # 遍历D文件夹下的所有文件
    for 文件名 in os.listdir(D文件夹路径):
        # 只处理.bin文件
        if  文件名.endswith('.BIN'):#文件名=='F0005.BIN':#文件名.endswith('.BIN'):
            文件路径 = os.path.join(D文件夹路径, 文件名)
            if os.path.exists(文件路径):
                # 调用处理函数
                extract_and_save(文件路径)
            else:
                print(f"文件 {文件名} 未找到！")