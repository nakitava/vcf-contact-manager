from flask import Flask, render_template, request, redirect, url_for, send_file
import vobject
import csv
import os
from io import StringIO, BytesIO

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'vcf'}

# Создаем папку для загрузок, если ее нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def parse_vcf(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        vcard_data = f.read()

    # Исправляем возможные проблемы в формате
    fixed_lines = []
    for line in vcard_data.splitlines():
        if line.startswith('TEL+') or line.startswith('TEL;'):
            line = line.replace('+ADs-', ';').replace('+AD0-', '=')
        fixed_lines.append(line)

    fixed_vcard_data = '\n'.join(fixed_lines)

    contacts = []
    for vcard in vobject.readComponents(fixed_vcard_data):
        contact = {
            'first_name': '',
            'last_name': '',
            'full_name': '',
            'org': '',
            'title': '',
            'tel_work': '',
            'tel_home': '',
            'tel_mobile': '',
            'email': '',
            'address': '',
            'note': '',
            'raw': str(vcard)
        }

        if 'fn' in vcard.contents:
            contact['full_name'] = str(vcard.fn.value)

        if 'n' in vcard.contents:
            name = vcard.n.value
            contact['first_name'] = name.given or ''
            contact['last_name'] = name.family or ''

        if 'org' in vcard.contents:
            contact['org'] = str(vcard.org.value[0]) if vcard.org.value else ''

        if 'title' in vcard.contents:
            contact['title'] = str(vcard.title.value)

        if 'tel' in vcard.contents:
            for tel in vcard.tel_list:
                tel_type = getattr(tel, 'type_param', '')
                if isinstance(tel_type, list):
                    tel_type = ','.join(tel_type)

                if 'WORK' in tel_type:
                    contact['tel_work'] = str(tel.value)
                elif 'HOME' in tel_type:
                    contact['tel_home'] = str(tel.value)
                elif 'CELL' in tel_type or 'MOBILE' in tel_type:
                    contact['tel_mobile'] = str(tel.value)

        if 'email' in vcard.contents:
            contact['email'] = str(vcard.email.value)

        if 'adr' in vcard.contents:
            address = vcard.adr.value
            contact['address'] = ' '.join(filter(None, [
                address.street, address.city, address.region, address.code, address.country
            ]))

        if 'note' in vcard.contents:
            contact['note'] = str(vcard.note.value)

        contacts.append(contact)

    return contacts


def save_vcf(filename, contacts):
    with open(filename, 'w', encoding='utf-8') as f:
        for contact in contacts:
            vcard = vobject.vCard()

            if contact['first_name'] or contact['last_name']:
                n = vcard.add('n')
                n.value = vobject.vcard.Name(
                    family=contact['last_name'],
                    given=contact['first_name']
                )

            if contact['first_name'] or contact['last_name']:
                fn = vcard.add('fn')
                fn.value = f"{contact['first_name']} {contact['last_name']}".strip()
            elif contact['org']:
                fn = vcard.add('fn')
                fn.value = contact['org']

            if contact['org']:
                org = vcard.add('org')
                org.value = [contact['org']]

            if contact['title']:
                title = vcard.add('title')
                title.value = contact['title']

            if contact['tel_work']:
                tel = vcard.add('tel')
                tel.value = contact['tel_work']
                tel.type_param = 'WORK'

            if contact['tel_home']:
                tel = vcard.add('tel')
                tel.value = contact['tel_home']
                tel.type_param = 'HOME'

            if contact['tel_mobile']:
                tel = vcard.add('tel')
                tel.value = contact['tel_mobile']
                tel.type_param = 'CELL'

            if contact['email']:
                email = vcard.add('email')
                email.value = contact['email']
                email.type_param = 'INTERNET'

            if contact['address']:
                adr = vcard.add('adr')
                adr.value = vobject.vcard.Address(street=contact['address'])
                adr.type_param = 'WORK'

            if contact['note']:
                note = vcard.add('note')
                note.value = contact['note']

            f.write(vcard.serialize())
            f.write('\n')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)

    if file and allowed_file(file.filename):
        filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
        file.save(filename)
        return redirect(url_for('view_contacts'))

    return redirect(request.url)


@app.route('/view')
def view_contacts():
    filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
    if not os.path.exists(filename):
        return redirect(url_for('index'))

    contacts = parse_vcf(filename)
    return render_template('view.html', contacts=contacts)


@app.route('/search', methods=['GET'])
def search_contacts():
    filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
    if not os.path.exists(filename):
        return redirect(url_for('index'))

    query = request.args.get('query', '').lower()
    contacts = parse_vcf(filename)

    if query:
        filtered = []
        for contact in contacts:
            if (query in contact['first_name'].lower() or
                    query in contact['last_name'].lower() or
                    query in contact['full_name'].lower() or
                    query in contact['org'].lower() or
                    query in contact['tel_work'].lower() or
                    query in contact['tel_mobile'].lower() or
                    query in contact['email'].lower()):
                filtered.append(contact)
        contacts = filtered

    return render_template('view.html', contacts=contacts, query=query)


@app.route('/edit/<int:index>', methods=['GET', 'POST'])
def edit_contact(index):
    filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
    if not os.path.exists(filename):
        return redirect(url_for('index'))

    contacts = parse_vcf(filename)

    if index < 0 or index >= len(contacts):
        return redirect(url_for('view_contacts'))

    if request.method == 'POST':
        contact = contacts[index]
        contact['first_name'] = request.form.get('first_name', '')
        contact['last_name'] = request.form.get('last_name', '')
        contact['org'] = request.form.get('org', '')
        contact['title'] = request.form.get('title', '')
        contact['tel_work'] = request.form.get('tel_work', '')
        contact['tel_home'] = request.form.get('tel_home', '')
        contact['tel_mobile'] = request.form.get('tel_mobile', '')
        contact['email'] = request.form.get('email', '')
        contact['address'] = request.form.get('address', '')
        contact['note'] = request.form.get('note', '')

        save_vcf(filename, contacts)
        return redirect(url_for('view_contacts'))

    return render_template('edit.html', contact=contacts[index], index=index)


@app.route('/delete/<int:index>')
def delete_contact(index):
    filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
    if not os.path.exists(filename):
        return redirect(url_for('index'))

    contacts = parse_vcf(filename)

    if index < 0 or index >= len(contacts):
        return redirect(url_for('view_contacts'))

    del contacts[index]
    save_vcf(filename, contacts)
    return redirect(url_for('view_contacts'))


@app.route('/add', methods=['GET', 'POST'])
def add_contact():
    if request.method == 'POST':
        filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
        contacts = parse_vcf(filename) if os.path.exists(filename) else []

        new_contact = {
            'first_name': request.form.get('first_name', ''),
            'last_name': request.form.get('last_name', ''),
            'org': request.form.get('org', ''),
            'title': request.form.get('title', ''),
            'tel_work': request.form.get('tel_work', ''),
            'tel_home': request.form.get('tel_home', ''),
            'tel_mobile': request.form.get('tel_mobile', ''),
            'email': request.form.get('email', ''),
            'address': request.form.get('address', ''),
            'note': request.form.get('note', ''),
            'raw': ''
        }

        contacts.append(new_contact)
        save_vcf(filename, contacts)
        return redirect(url_for('view_contacts'))

    return render_template('add.html')


@app.route('/export/vcf')
def export_vcf():
    filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
    if not os.path.exists(filename):
        return redirect(url_for('index'))

    return send_file(
        filename,
        as_attachment=True,
        download_name='contacts_export.vcf',
        mimetype='text/vcard'
    )


@app.route('/export/csv')
def export_csv():
    filename = os.path.join(app.config['UPLOAD_FOLDER'], 'contacts.vcf')
    if not os.path.exists(filename):
        return redirect(url_for('index'))

    contacts = parse_vcf(filename)

    # Создаем временный файл в памяти
    output = StringIO()
    writer = csv.writer(output)

    # Заголовки CSV
    writer.writerow([
        'First Name', 'Last Name', 'Organization', 'Title',
        'Work Phone', 'Home Phone', 'Mobile Phone',
        'Email', 'Address', 'Note'
    ])

    # Данные контактов
    for contact in contacts:
        writer.writerow([
            contact['first_name'], contact['last_name'], contact['org'], contact['title'],
            contact['tel_work'], contact['tel_home'], contact['tel_mobile'],
            contact['email'], contact['address'], contact['note']
        ])

    # Создаем BytesIO объект для отправки
    mem = BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    output.close()

    return send_file(
        mem,
        as_attachment=True,
        download_name='contacts_export.csv',
        mimetype='text/csv'
    )


if __name__ == '__main__':
    app.run(debug=True)