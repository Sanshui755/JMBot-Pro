import PyPDF2

def set_password_pdf(input_pdf, output_pdf, password):
    # 打开输入的PDF文件
    with open(input_pdf, "rb") as file:
        reader = PyPDF2.PdfReader(file)
        writer = PyPDF2.PdfWriter()

        # 将所有页面添加到新的PDF文件中
        for page in reader.pages:
            writer.add_page(page)

        # 设置密码
        writer.encrypt(password)

        # 写入新的PDF文件
        with open(output_pdf, "wb") as output_file:
            writer.write(output_file)

if __name__ == "__main__":
    input_pdf = r"1059954.pdf"  # 输入的PDF文件名
    output_pdf = "output.pdf"  # 输出的PDF文件名
    password = "114514"  # 设置的密码

    set_password_pdf(input_pdf, output_pdf, password)
    print(f"PDF文件已成功加密并保存为 {output_pdf}")