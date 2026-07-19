import os
import struct
import pandas as pd

def 读取码表文件(文件路径):
    码表字典= {}
    with open(文件路径, "r", encoding="utf-16le") as 文本码表:
         码表内容 = 文本码表.read()
    for  行 in 码表内容.splitlines():
         码值, 等号, 文字 = 行.partition('=')
         码表字典[码值] = 文字
    return 码表字典

def 读取字节(N,ROM):
    #try:
        缓存字节=''
        while     N>0:
                  读取字节=format(ROM.read(1)[0], '02x').upper()
                  缓存字节+=读取字节
                  N-=1
        读取字节=缓存字节
    #except:
    #    print(子文件夹名, ROM.tell())
    #    读取字节=''
        return 读取字节

def 提取指针列表(ROM):
    """从文件中提取所有指针，并返回去重后的指针列表。"""
    指针列表 = []
    ROM.seek(0)  # 从文件开头开始读取
    初始指针=读取字节(4, ROM)
    指针列表.append(初始指针)
    初始地址=初始指针[6:8]+初始指针[4:6]+初始指针[2:4]+初始指针[0:2]
    段数=int(初始地址,16)//4-1
    while 段数>0:
        指针 = 读取字节(4, ROM)
        指针列表.append(指针)
        段数-=1
    return 指针列表


def 处理文件夹(文件夹路径):
    """处理文件夹中的所有 .bin 文件，并生成 Excel 文件。"""
    数据列表 = []
    字数=0
    for 文件名 in os.listdir(文件夹路径):
        if 文件名.endswith('.bin'):
            文件路径 = os.path.join(文件夹路径, 文件名)
            with open(文件路径, 'rb') as ROM:
                指针列表= 提取指针列表(ROM)
                for STR指针 in 指针列表:
                    文本=''
                    文本地址=STR指针[6:8]+STR指针[4:6]+STR指针[2:4]+STR指针[0:2]
                    ROM.seek(int(文本地址,16))
                    while True:
                        单字节=读取字节(1,ROM)
                        if  单字节 in 码表字典:
                            文本 += 码表字典[单字节] 
                        elif 单字节 not in 码表字典:
                            第二字节=读取字节(1,ROM)
                            组合字节=单字节+第二字节
                            if  组合字节 in 码表字典:
                                文本 += 码表字典[组合字节] 
                                字数+=1
                            elif 组合字节=='00FF':
                                文本+='{00FF}'  
                            elif 组合字节=='01FF':
                                文本+=f"▽\n"
                            elif 组合字节=='02FF':
                                文本+=f"※※※※※※※\n"
                            elif 组合字节=='03FF':
                                文本+=f"\n"
                            elif 组合字节=='04FF':
                                文本+='{主角}'
                            elif 组合字节=='05FF':
                                文本+='{队友}'
                            elif 组合字节=='18FF':
                                文本+='{名字1}'   
                            elif 组合字节=='19FF':
                                文本+='{名字4}'   
                            elif 组合字节=='1BFF':
                                文本+='{道具}'        
                            elif 组合字节=='67FF':
                                文本+='{种族1}'      
                            elif 组合字节=='68FF':
                                文本+='{种族2}'       
                            elif 组合字节=='6FFF':
                                文本+='{主角等人}'
                            elif 组合字节=='71FF':
                                文本+='{数值0}'    
                            elif 组合字节=='72FF':
                                文本+='{72FF}}'   
                            elif 组合字节=='73FF':
                                文本+='{73FF}}'   
                            elif 组合字节=='76FF':
                                文本+='{数值1}'         
                            elif 组合字节=='77FF':
                                文本+='{名字3}'   
                            elif 组合字节=='78FF':
                                文本+='{种族3}'   
                            elif 组合字节=='7AFF':
                                文本+='{恶魔1}'   
                            elif 组合字节=='7BFF':
                                文本+='{魔法}'   
                            elif 组合字节=='7CFF':
                                文本+='/'
                            elif 组合字节=='7DFF':
                                文本+='{名字2}'   
                            elif 组合字节=='70FF':
                                文本+='{仲魔}'    
                            elif 组合字节=='7FFF':
                                文本+='{恶魔2}'        
                            elif 组合字节=='88FF':
                                文本+='{数量}'      
                            elif 组合字节=='92FF':
                                文本+='{大停顿}'       
                            elif 组合字节=='FEFF':
                                文本+='　'
                            elif 组合字节=='FFFF':
                                break
                            else :
                                文本 += f"{{{组合字节}}}"
                                print(组合字节)
                    文件名=文件名[0:8]
                    # 将文件夹名称、文件名、指针和文本存入列表
                    数据列表.append([子文件夹名, 文件名, 文本地址, 文本])
    return 数据列表, 字数




# 获取当前脚本所在的目录
目录 = os.path.dirname(os.path.abspath(__file__))
# 构造文本文件夹的路径
文本文件夹路径 = os.path.join(目录, '文本')
码表文件  =os.path.join(目录, '原始码表.txt')
码表字典=读取码表文件(码表文件)

# 检查文本文件夹是否存在
if not os.path.exists(文本文件夹路径):
    print(f"文本文件夹未找到: {文本文件夹路径}")
else:
    # 创建 Excel 文件
    输出文件名 = os.path.join(文本文件夹路径, '导出文本.xlsx')
    with pd.ExcelWriter(输出文件名, engine='xlsxwriter') as 写入器:
        # 遍历文本文件夹下的所有子文件夹
        总字数 = 0
        总数据列表 = []
        for 子文件夹名 in os.listdir(文本文件夹路径):
            子文件夹路径 = os.path.join(文本文件夹路径, 子文件夹名)
            # 如果是文件夹（而非文件），则调用处理函数
            if os.path.isdir(子文件夹路径):
                数据列表, 字数 = 处理文件夹(子文件夹路径)
                总字数 += 字数
                总数据列表.extend(数据列表)  # 将当前文件夹的数据添加到总数据列表
                print(f"子文件夹 {子文件夹名} 处理完成，字数: {字数}")
            else:
                print(f"跳过文件: {子文件夹路径}")

        # 创建 DataFrame
        df = pd.DataFrame(总数据列表, columns=['文件夹名称', '文件名', '指针', '文本'])
        # 将数据写入 Excel 文件的 Sheet
        df.to_excel(写入器, index=False, sheet_name='导出文本')
        # 获取工作簿和工作表对象
        工作簿 = 写入器.book
        工作表 = 写入器.sheets['导出文本']
        # 设置列宽和单元格格式
        格式 = 工作簿.add_format({'text_wrap': True})  # 自动换行格式
        工作表.set_column('A:A', width=20)  # 设置第一列宽度
        工作表.set_column('B:B', width=20)  # 设置第二列宽度
        工作表.set_column('C:C', width=20)  # 设置第三列宽度
        工作表.set_column('D:D', width=64, cell_format=格式)  # 设置第四列宽度

    print(f"所有子文件夹处理完成，总字数: {总字数}，Excel 文件已保存: {输出文件名}")