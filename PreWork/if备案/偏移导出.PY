#基址加偏移
import binascii
import xlwings as xw
import xlsxwriter
import re
import win32com.client
import os
import psutil


def 读取初始码表文件(文件路径):
    码表字典= {}
    with open(文件路径, "r", encoding="utf-16le") as 文本码表:
         码表内容 = 文本码表.read()
    for  行 in 码表内容.splitlines():
         码值, 等号, 文字 = 行.partition('=')
         码表字典[码值] = 文字
    return 码表字典


def 读取字节(N,ROM):
     缓存字节=''
     while     N>0:
               读取字节=format(ROM.read(1)[0], '02x').upper()
               缓存字节+=读取字节
               N-=1
     读取字节=缓存字节
     return 读取字节
def 关闭Excel进程():
    # 遍历所有进程
    for proc in psutil.process_iter():
        try:
            # 检查进程名是否为 Excel
            if "EXCEL" in proc.name():
                print(f"发现 Excel 进程，PID: {proc.pid}，尝试关闭...")
                proc.terminate()  # 终止进程
                print("Excel 进程已关闭。")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def  读取地址列表(原始文件路径,偏移开始地址,偏移结束地址,文本基址):
     文本地址列表= []
     偏移地址列表=[]
     i=0
     with open(原始文件路径, "rb") as ROM:
          ROM.seek(偏移开始地址)
          二进制数据=ROM.read(偏移结束地址-偏移开始地址)
          偏移数据=binascii.hexlify(二进制数据).decode().upper()
          while     i < len(偏移数据):
                    偏移地址=hex(偏移开始地址+i//2)[2:].zfill(8).upper()
                    偏移地址列表.append(偏移地址)
                    偏移=int(偏移数据[i+6:i+8]+偏移数据[i+4:i+6]+偏移数据[i+2:i+4]+偏移数据[i:i+2], 16)
                    i+=8
                    文本地址=文本基址+偏移
                    文本地址列表.append(文本地址)
          return    文本地址列表,偏移地址列表


def 读取文本(文本地址,原始文件路径):
     文本=''  
     文本=开始读取(文本,文本地址)                         
     return    文本
def  开始读取(文本,文本地址):
     with open(原始文件路径, "rb") as ROM:
          数据=ROM.read()
          数据长度=len(数据)
          ROM.seek(文本地址)
          while     ROM.tell()<数据长度:
               单字节=读取字节(1,ROM)
               if   单字节 in 码表字典:
                    文本 += 码表字典[单字节] 
               elif 单字节 not in 码表字典:
                    第二字节=读取字节(1,ROM)
                    组合字节=单字节+第二字节
                    if  组合字节 in 码表字典:
                        文本 += 码表字典[组合字节] 
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
     return    文本

def 建立EXCEL文件(导出文件路径):
    工作簿=xlsxwriter.Workbook(导出文件路径)
    工作表=工作簿.add_worksheet()
    黄色=工作簿.add_format({'color': 'yellow'})
    红色=工作簿.add_format({'color': 'red'})
    绿色=工作簿.add_format({'color': 'green'})
    灰色=工作簿.add_format({'color': 'grey'})
    黑色=工作簿.add_format({'color': 'black'})
    紫色=工作簿.add_format({'color': 'purple'})
    默认=工作簿.add_format({'color': 'black','text_wrap': True})
    蓝色=工作簿.add_format({'color': 'blue'})
    # 设置每列的宽度，并将text_wrap属性设置为True
    工作表.set_column(2,3,width=64, cell_format=工作簿.add_format({'text_wrap': True}))
    return 工作簿,工作表

# 获取当前脚本所在的目录
目录= os.path.dirname(os.path.abspath(__file__))
# 构造Excel文件的相对路径
原始文件路径=os.path.join(目录, 'F0088.bin')
导出文件路径=os.path.join(目录, '导出文本.xlsx')
码表路径=os.path.join(目录, '原始码表.txt')
码表字典=读取初始码表文件(码表路径)



偏移开始地址=     0x42B4
偏移结束地址=     0x42D8
文本基址=0x42B4

文本地址列表,偏移地址列表=读取地址列表(原始文件路径,偏移开始地址,偏移结束地址,文本基址)
#字典列表=读取字典(原始文件路径)
文本列表= []
for  文本地址 in 文本地址列表:
     print(文本地址)
     初始文本=读取文本(文本地址,原始文件路径)
     文本列表.append(初始文本)
关闭Excel进程()
工作簿,工作表=建立EXCEL文件(导出文件路径)
for 行号, 文本地址 in enumerate(文本地址列表):
    文本地址=hex(文本地址)[2:].zfill(8).upper()
    工作表.write(行号, 1, 文本地址)
for 行号, 文本地址 in enumerate(偏移地址列表):
    工作表.write(行号, 0, 文本地址)
for 行号, 文本 in enumerate(文本列表):
    工作表.write(行号, 2, 文本)

工作簿.close()