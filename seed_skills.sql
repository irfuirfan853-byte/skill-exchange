-- ============================================================
--  SKILL EXCHANGE — Starter Skill Catalog
--  Loads ~120 popular skills so every dropdown/search has data.
--  Run after schema.sql:
--      mysql -u root -p skill_exchange < seed_skills.sql
--  Safe to run again (uses INSERT IGNORE).
-- ============================================================

USE skill_exchange;

INSERT IGNORE INTO skills (name, category) VALUES
-- Programming & Tech
('Python',                 'Programming & Tech'),
('JavaScript',             'Programming & Tech'),
('HTML & CSS',             'Programming & Tech'),
('React',                  'Programming & Tech'),
('Node.js',                'Programming & Tech'),
('SQL / Databases',        'Programming & Tech'),
('Java',                   'Programming & Tech'),
('C++',                    'Programming & Tech'),
('C#',                     'Programming & Tech'),
('PHP',                    'Programming & Tech'),
('Flutter',                'Programming & Tech'),
('Android Development',    'Programming & Tech'),
('iOS Development',        'Programming & Tech'),
('Data Science',           'Programming & Tech'),
('Machine Learning',       'Programming & Tech'),
('Cyber Security',         'Programming & Tech'),
('Cloud Computing (AWS)',  'Programming & Tech'),
('Git & GitHub',           'Programming & Tech'),
('Excel (Advanced)',       'Programming & Tech'),
('WordPress',              'Programming & Tech'),
('Game Development',       'Programming & Tech'),
('Arduino / Electronics',  'Programming & Tech'),

-- Design & Creative
('UI / UX Design',         'Design & Creative'),
('Graphic Design',         'Design & Creative'),
('Photoshop',              'Design & Creative'),
('Illustrator',            'Design & Creative'),
('Video Editing',          'Design & Creative'),
('Animation',              'Design & Creative'),
('Figma',                  'Design & Creative'),
('Logo Design',            'Design & Creative'),
('Photography',            'Design & Creative'),
('Drawing & Sketching',    'Design & Creative'),
('3D Modeling',            'Design & Creative'),
('Canva Design',           'Design & Creative'),

-- Languages
('English',                'Languages'),
('Spanish',                'Languages'),
('French',                 'Languages'),
('German',                 'Languages'),
('Hindi',                  'Languages'),
('Arabic',                 'Languages'),
('Chinese (Mandarin)',     'Languages'),
('Japanese',               'Languages'),
('Korean',                 'Languages'),
('Tamil',                  'Languages'),
('Telugu',                 'Languages'),
('Urdu',                   'Languages'),
('Portuguese',             'Languages'),
('Russian',                'Languages'),
('IELTS Preparation',      'Languages'),

-- Music & Arts
('Guitar',                 'Music & Arts'),
('Piano',                  'Music & Arts'),
('Singing',                'Music & Arts'),
('Music Production',       'Music & Arts'),
('Beatboxing',             'Music & Arts'),
('Dance',                  'Music & Arts'),
('Digital Art',            'Music & Arts'),
('Chess',                  'Music & Arts'),
('Origami',                'Music & Arts'),

-- Business & Career
('Digital Marketing',      'Business & Career'),
('SEO',                    'Business & Career'),
('Social Media Marketing', 'Business & Career'),
('Public Speaking',        'Business & Career'),
('Resume Writing',         'Business & Career'),
('Financial Literacy',     'Business & Career'),
('Stock Trading',          'Business & Career'),
('Entrepreneurship',       'Business & Career'),
('Project Management',     'Business & Career'),
('Microsoft Office',       'Business & Career'),
('Accounting Basics',      'Business & Career'),

-- Sports & Fitness
('Fitness Training',       'Sports & Fitness'),
('Yoga',                   'Sports & Fitness'),
('Swimming',               'Sports & Fitness'),
('Meditation',             'Sports & Fitness'),
('Badminton',              'Sports & Fitness'),
('Cricket',                'Sports & Fitness'),
('Football / Soccer',      'Sports & Fitness'),
('Basketball',             'Sports & Fitness'),
('Boxing',                 'Sports & Fitness'),
('Martial Arts',           'Sports & Fitness'),

-- Academics
('Mathematics',            'Academics'),
('Physics',                'Academics'),
('Chemistry',              'Academics'),
('Biology',                'Academics'),
('History',                'Academics'),
('Economics',              'Academics'),
('English Literature',     'Academics'),
('Accounting',             'Academics'),
('Geography',              'Academics'),
('Psychology',             'Academics'),

-- Food & Lifestyle
('Cooking & Baking',       'Food & Lifestyle'),
('Baking',                 'Food & Lifestyle'),
('Gardening',              'Food & Lifestyle'),
('DIY Home Repair',        'Food & Lifestyle'),
('Tailoring / Sewing',     'Food & Lifestyle'),
('Driving',                'Food & Lifestyle'),
('Personal Finance',       'Food & Lifestyle'),
('Time Management',        'Food & Lifestyle');
