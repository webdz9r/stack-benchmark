SELECT 'contacts', id, first_name, last_name, company, job_title, coalesce(birthday,'<null>'), notes, favorite FROM contacts ORDER BY id;
SELECT 'emails', contact_id, position, label, value FROM emails ORDER BY contact_id, position;
SELECT 'phones', contact_id, position, label, value FROM phones ORDER BY contact_id, position;
SELECT 'addresses', contact_id, position, label, street, city, region, postal_code, country FROM addresses ORDER BY contact_id, position;
SELECT 'tags', id, name, color FROM tags ORDER BY id;
SELECT 'contact_tags', contact_id, tag_id FROM contact_tags ORDER BY contact_id, tag_id;
SELECT 'fts', rowid, name, company, emails, phones, places, notes FROM contacts_fts ORDER BY rowid;
