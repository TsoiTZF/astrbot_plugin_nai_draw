"""来自 quicktagcloud 构图风格法典的独立随机完整场景池。

来源：composition_style，版本 2025.10.19，作者凉夏之夜。
仅由显式随机功能使用，普通 /nai 描述不会自动注入。
"""

import random
import re

COMPOSITION_SOURCE = {
    "codex": "composition_style",
    "version": "2025.10.19",
    "author": "凉夏之夜",
    "url": "https://novelai.quicktagcloud.com/?codex=composition_style",
}

COMPOSITION_SCENES = (
    (
        '运河小船上的静谧时刻',
        'sitting in a small wooden boat on a calm canal, 1.3::medium shot, eye-level::, trailing her fingertips in the water with a dreamy, serene smile, wearing a pretty pink dress, 1.5::the cherry blossom trees on both banks form a spectacular pink tunnel overhead, covering the sky::, 1.4::the water surface is covered with floating petals and perfectly reflects the pink blossoms, creating an overwhelmingly romantic and magical atmosphere::',
        'composition_style_0001',
    ),
    (
        '九份夜巷里的热汤回眸',
        'in a bustling, narrow old street with stone stairs at night, reminiscent of Jiufen, Taiwan, 1.2::medium shot, from a slightly high angle::, holding a bowl of hot taro ball soup with a happy and curious expression, wearing a simple dress and a jacket, 1.5::the entire scene is illuminated by the iconic warm, red glow from hundreds of traditional paper lanterns hanging overhead::, 1.2::the background is a dense crowd of people and traditional teahouses, creating a lively, festive, and nostalgic atmosphere::',
        'composition_style_0002',
    ),
    (
        '新年市集里的糖果笑脸',
        'at a bustling chinese new year market on a historic street at sunset, 1.3::close-up on her face::, holding a small bag of traditional candies with a bright, excited smile, looking at the festive decorations, wearing a modern dress and a warm jacket, 1.5::the warm, golden light of the sunset mixes with the red glow from lanterns and decorations, creating a rich, saturated, and festive color palette::, 1.2::a dense crowd and piles of new year goods are blurred into a lively bokeh background::',
        'composition_style_0003',
    ),
    (
        '台式夜市游戏摊前',
        'at a lively taiwanese night market, 1.2::cowboy shot, three-quarter view::, crouching in front of a brightly lit game stall, completely absorbed in playing with a look of focused excitement, wearing a casual dress and a jacket, 1.5::the scene is vibrantly illuminated by the colorful, harsh lights of the game stall itself, creating a fun and energetic atmosphere::, 1.2::the background is a blur of the night market crowd, food stalls, and other neon signs, slice of life, playful mood::',
        'composition_style_0004',
    ),
    (
        '平溪铁轨旁写天灯',
        'on a railway track in a small town like Pingxi, Taiwan at sunset, 1.3::medium shot, eye-level::, carefully writing wishes on a large sky lantern with a brush, a sincere and hopeful smile on her face, wearing a dress and a jacket, 1.4::the soft, golden light of the setting sun bathes the scene, while in the background, a few lit sky lanterns are beginning to float into the twilight sky::, 1.2::a bustling crowd and old street shops are blurred in the background, magical, hopeful, transitional atmosphere::',
        'composition_style_0005',
    ),
    (
        '便利店夏夜吃冰棒',
        'leaning against the glass door of a 24-hour convenience store on a humid summer night, 1.2::medium shot, eye-level::, eating a fruit popsicle with a content and relaxed expression, wearing a simple summer slip dress, 1.4::the bright interior light of the store creates a strong, beautiful rim light on her figure::, 1.2::the pavement outside is wet after rain, creating vibrant reflections, slice of life, quiet urban night atmosphere::',
        'composition_style_0006',
    ),
    (
        '秋夜露天电影节回眸',
        'at an elegant outdoor film festival at night in autumn, 1.3::close-up on her face::, sitting in the audience and turning back with a gentle, dreamy smile, wearing a glamorous champagne-colored evening gown, 1.5::her face is softly illuminated by the cinematic light from the giant movie screen (off-screen), which reflects in her eyes::, 1.2::the visible beam of light from a projector cuts through the dark air behind her, romantic, magical atmosphere, bokeh background of other people::',
        'composition_style_0007',
    ),
    (
        '云海新月上的钓星少女',
        'in a dreamy realm, 1.2::medium shot, eye-level::, sitting on a glowing crescent moon that floats on a sea of clouds, fishing for stars with a simple rod, a serene and curious expression, wearing a magical dress made of shifting flower petals, 1.5::the area below is a vast, rolling sea of soft clouds, with schools of small, glowing stars swimming within it::, 1.2::the sky is a soft pastel gradient of pink and purple, whimsical, magical, and peaceful atmosphere::',
        'composition_style_0008',
    ),
    (
        '海边露台的月夜舞步',
        'dancing gracefully on a seaside terrace at night, 1.2::medium shot, from a slightly low angle::, one arm elegantly raised in a dance pose, an elegant and confident smile, wearing a beautiful off-the-shoulder white dress with a flowing sash, 1.4::the foreground is framed by white rose bushes::, 1.3::in the background, the sea is sparkling, with the brightly lit skyline of a distant city across the water, the sky is full of stars and a faint milky way::, magical, romantic, ethereal atmosphere, cinematic lighting,',
        'composition_style_0009',
    ),
    (
        '书店木架旁整理书册',
        'working as a clerk in a cozy bookstore, 1.3::close-up, from the side::, arranging books neatly on a wooden bookshelf with a gentle, kind smile, wearing a canvas apron over a long-sleeve dress, 1.5::warm afternoon sunlight slants through a large window, creating beautiful, visible light beams and highlighting floating dust particles::, 1.2::the background is filled with tall, blurry bookshelves, creating a scholarly and peaceful atmosphere, slice of life::',
        'composition_style_0010',
    ),
    (
        '枫林里仰光微笑',
        'standing in a vibrant maple forest in autumn, 1.2::medium shot, eye-level::, tilting her face up towards the sun with her eyes closed and a pure, happy smile, wearing a light dress and an open beige jacket, 1.5::sunlight filters through the fiery red maple leaves overhead, casting a beautiful, warm, dappled light across her face and clothes::, 1.3::the air is filled with slowly falling red leaves, the ground is covered in a thick carpet of leaves, rich autumn colors, peaceful and heartwarming atmosphere::',
        'composition_style_0011',
    ),
    (
        '花店工作台前修剪玫瑰',
        'working as a florist in a charming flower shop, 1.3::tight medium shot, eye-level::, standing behind a workbench and trimming a bouquet of roses with a focused, gentle smile, wearing a dark green waterproof apron over a dress, 1.4::the workbench is beautifully cluttered with various colorful flowers, leaves, and wrapping papers::, 1.2::bright, natural daylight floods the shop, the background is a blur of countless flowers in vases, creative and fragrant atmosphere::',
        'composition_style_0012',
    ),
    (
        '黄昏大学天台眺望城市',
        'on a university rooftop at dusk, 1.2::medium shot, from the side::, leaning on the railing and looking out at the city with a calm, relaxed expression, wearing a beige cardigan, a white shirt, a pleated miniskirt, and black tights, 1.5::the low-angle golden hour sun creates a beautiful, warm rim light on her hair and silhouette::, 1.2::the background is a sprawling cityscape bathed in the warm glow of sunset, peaceful, academic, autumn atmosphere::',
        'composition_style_0013',
    ),
    (
        '公寓阳台吹晚风',
        'on a modern apartment balcony at dusk, 1.3::close-up on her face and upper body::, leaning against the railing with her eyes closed, enjoying the evening breeze with a cozy, languid expression, wearing a white slip dress under a long, oversized beige cardigan, 1.4::the twinkling lights of the distant city create a beautiful, colorful bokeh background::, 1.2::a warm and intimate atmosphere, slice of life, peaceful end to the day::',
        'composition_style_0014',
    ),
    (
        '秋林溪边俯身触水',
        "sitting on a mossy stone by a clear stream in an autumn forest at golden hour, 1.2::medium shot, from a high angle::, dipping her fingertips into the cool water with a quiet, thoughtful expression, wearing a long-sleeved dress, 1.5::many vibrant red maple leaves are floating on the water's surface, carried by the gentle current::, 1.3::golden sunlight filters through the autumn trees, creating sparkling reflections on the water, serene, poetic atmosphere::",
        'composition_style_0015',
    ),
    (
        '夕阳河桥上的回眸',
        'leaning against the railing of a bridge over a river at sunset, 1.2::cowboy shot, three-quarter view::, looking back at the viewer with a gentle, bright smile, wearing a long-sleeved sailor school uniform, her school bag slung over her shoulder, 1.5::the sky is painted in brilliant orange and pink hues, which are perfectly reflected in the calm river below::, 1.2::city lights begin to twinkle in the distance, beautiful, nostalgic, after-school atmosphere::',
        'composition_style_0016',
    ),
    (
        '冬日客厅沙发阅读',
        'curled up on a sofa inside a modern living room on a sunny winter day, 1.3::close-up on her face and the book::, reading a book with a focused and peaceful expression, wearing a cozy, oversized, chunky cable-knit sweater, 1.5::a patch of bright, warm winter sunlight streams through a large window, enveloping her in a golden glow::, 1.3::dust particles are visible dancing in the sunbeam, creating a tranquil and heartwarming atmosphere, clean and bright interior::',
        'composition_style_0017',
    ),
    (
        '山间小站与复古红车',
        'standing on a quaint mountain railway platform in spring, 1.2::cowboy shot, eye-level::, holding down her skirt with a gentle, nostalgic smile as a vintage red train passes by, wearing a graceful white dress, 1.5::the passing train creates a spectacular blizzard of swirling cherry blossom petals that fills the air::, 1.3::the railway tracks are lined with blooming sakura trees, bright sunny day, beautiful, cinematic atmosphere::',
        'composition_style_0018',
    ),
    (
        '明亮咖啡馆靠窗独坐',
        "sitting in a bright, minimalist cafe, 1.2::medium shot, from the side::, holding a cup of latte and gazing peacefully out the window, wearing a crisp, oversized white shirt, 1.5::a giant, magnificent cherry blossom tree in full, vibrant bloom is perfectly framed by the large floor-to-ceiling window::, 1.3::the clean glass has a faint reflection of the cafe's interior, serene, aesthetic, slice of life atmosphere::",
        'composition_style_0019',
    ),
    (
        '夜樱灯下仰望',
        'strolling through a park at night during a sakura festival, 1.3::close-up on her face, from a low angle::, looking up at the illuminated blossoms with an expression of awe and wonder, wearing an elegant lavender dress, 1.5::the cherry blossom trees are lit from below by spotlights, making the petals glow with an ethereal, magical pink light::, 1.3::the unique uplighting casts soft, dramatic shadows on her face, yozakura (night sakura) atmosphere, beautiful, cinematic::',
        'composition_style_0020',
    ),
    (
        '日式房间里的插花练习',
        'in a bright, minimalist Japanese-style room, 1.2::tight medium shot, eye-level::, kneeling on the floor, practicing ikebana with intense, serene concentration, carefully placing a single cherry blossom branch into a ceramic vase, wearing a simple white shirt with rolled-up sleeves, 1.4::the scene is filled with soft, diffused natural light coming from a large shoji screen in the background::, 1.2::zen atmosphere, peaceful, artistic, focus on the beauty of simplicity::',
        'composition_style_0021',
    ),
    (
        '暴雨公交亭里的独处',
        'sitting alone in a bus shelter during a heavy summer thunderstorm, 1.2::medium shot, from within the shelter::, looking out at the rain with a calm and focused expression, her school bag beside her, wearing a short-sleeved school uniform, 1.5::a torrential downpour creates a curtain of rain just outside the shelter, blurring the street scene::, 1.3::reflections of streetlights and car headlights shimmer on the wet road, creating a strong contrast between the safe interior and the stormy exterior, atmospheric, cinematic::',
        'composition_style_0022',
    ),
    (
        '雨天窗上画心',
        'in a bright, modern living room on a rainy day, 1.3::close-up on her face and hand::, drawing a heart on a foggy window pane with her finger, a gentle and playful smile on her face, wearing a comfortable linen house dress, 1.5::the window is covered in a beautiful layer of condensation, and the lines she draws are sharp and clear::, 1.2::the rainy, blurry view outside the window is visible through her drawing, cozy, heartwarming, quiet afternoon atmosphere::',
        'composition_style_0023',
    ),
    (
        '雨后寺院撑伞漫步',
        'in a traditional temple courtyard right after a summer rain, 1.2::cowboy shot, from a slightly low angle::, holding an umbrella and walking carefully on the wet pavement, a serene and refreshed expression, wearing a summer school uniform, 1.5::the wet stone pavement is highly reflective, creating a perfect mirror image of the temple architecture and the clearing sky::, 1.3::water is dripping from the traditional eaves, the air is crisp and clean, beautiful, spiritual atmosphere::',
        'composition_style_0024',
    ),
    (
        '老天文台前窥望星空',
        'at an old observatory at night, 1.3::close-up on her face and the telescope::, on tiptoes, looking through the eyepiece of a giant vintage brass telescope with an expression of awe and curiosity, wearing a khaki trench coat, 1.4::the observatory dome is open, revealing a spectacular starry sky with a clear milky way::, 1.2::the scene is dimly lit by starlight and faint work lights, creating a mysterious and scholarly atmosphere, cinematic lighting::',
        'composition_style_0025',
    ),
    (
        '金色屋顶上的吉他',
        'on a city rooftop at golden hour, 1.2::medium shot, eye-level::, sitting on a chair with her eyes closed, immersed in playing an acoustic guitar, wearing an oversized beige hoodie, 1.5::the entire scene is bathed in the warm, saturated light of the setting sun, creating a beautiful, nostalgic atmosphere::, 1.2::the silhouette of the city skyline is visible in the background, along with a water tower and some potted plants, slice of life, indie musician vibe::',
        'composition_style_0026',
    ),
    (
        '阳光画室里的成品审视',
        'in a bright, sun-drenched art studio, 1.2::cowboy shot, from behind and to the side::, leaning against a large window frame with her arms crossed, appraising a freshly finished painting on an easel with a focused expression, wearing an oversized white shirt splattered with paint, 1.4::the room is filled with bright, natural light, illuminating the textures of the canvas and the colors on a nearby palette::, 1.2::art supplies, brushes, and other paintings are scattered around, creating a creative and authentic atmosphere::',
        'composition_style_0027',
    ),
    (
        '时间静止房间里的惊奇',
        'in a room where time is frozen, 1.3::close-up on her face and hand::, reaching out cautiously to touch a sugar cube that is suspended in mid-air, an expression of utter surprise and awe, wearing an elegant afternoon tea dress, 1.5::a stream of tea pouring from a teapot is also frozen mid-air, forming a static arc of liquid, dust particles and even a bird outside the window are motionless::, 1.2::sunlight beams are solidified in the air, creating a surreal, magical, and eerie atmosphere, cinematic lighting::',
        'composition_style_0028',
    ),
    (
        '清晨花市挑选盆栽',
        'at a bustling city flower market in the early morning, 1.3::close-up on her face and hands::, carefully examining a small potted plant with a focused and gentle smile, wearing a simple dress and a light denim jacket, 1.5::the foreground and background are filled with a vibrant bokeh of countless colorful flowers and plants, creating a beautiful natural frame::, 1.2::the soft morning light makes the scene bright and fresh, heartwarming, slice of life atmosphere::',
        'composition_style_0029',
    ),
    (
        '春日草坪吹蒲公英',
        'sitting on a lush green campus lawn on a sunny spring afternoon, 1.4::extreme close-up on her face and the dandelion::, holding a detailed dandelion puff close to her lips, about to blow the seeds with a hopeful and playful expression, wearing a summer school uniform, 1.5::the delicate, translucent seeds of the dandelion are in sharp focus::, 1.2::the background is a beautiful bokeh of the green grass and a grand library building, youthful, nostalgic, slice of life atmosphere::',
        'composition_style_0030',
    ),
    (
        '雨后山径与指尖蝴蝶',
        "on a mountain trail after a spring rain, 1.3::close-up, focusing on her hand and the butterfly::, a beautiful, detailed butterfly is resting on her outstretched index finger, her face is in profile in the background with an expression of gentle surprise, wearing a functional windbreaker, 1.5::the butterfly's intricate wing patterns are in sharp focus::, 1.3::glistening raindrops hang on the vibrant green leaves all around, creating a fresh, serene, and magical atmosphere of connection with nature::",
        'composition_style_0031',
    ),
    (
        '黄昏屋顶花园浇花',
        'watering plants in a rooftop garden at dusk, 1.2::medium shot, from a low angle::, holding a watering can with a content and loving smile, wearing a comfortable house dress, 1.5::the golden hour sunset light filters through the water droplets from the can, making them sparkle like gold::, 1.3::the background is a vast, beautiful sky painted in pink and purple hues, with the city skyline as a distant silhouette, peaceful, nurturing, urban farming atmosphere::',
        'composition_style_0032',
    ),
    (
        '雷雨后捷运站台小憩',
        'leaning against a pillar on an open-air MRT station platform after a summer thunderstorm, 1.2::medium shot, eye-level::, fanning herself with a book, a calm and slightly languid expression, wearing a summer school uniform, 1.4::the platform is wet and reflective, mirroring the clearing sky and station lights, creating a humid and steamy atmosphere::, 1.2::modern architecture of the station, blurry city view in the background, slice of life, tranquil urban moment::',
        'composition_style_0033',
    ),
    (
        '台式夜市里的珍珠奶茶回眸',
        'in a bustling taiwanese night market, 1.3::close-up on her face::, looking back over her shoulder with a bright, happy smile while holding a cup of bubble tea, wearing a simple summer dress, 1.5::the background is a vibrant, colorful bokeh of countless night market stalls, signs, and lights, creating a lively atmosphere::, 1.2::condensation droplets are visible on the cold drink cup, energetic, slice of life, foodie moment::',
        'composition_style_0034',
    ),
    (
        '日落海边咖啡馆发呆',
        'sitting at a rustic beachside cafe at sunset, 1.2::medium shot, from the side::, resting her chin on her hand and gazing at the ocean with a serene, relaxed expression, wearing a semi-transparent white cover-up over her swimsuit, 1.5::a brilliant sunset is happening over the ocean, painting the sky in vibrant orange and purple hues::, 1.3::the sea breeze is gently blowing her slightly wet hair and the fabric of her cover-up, tranquil, tropical, beautiful atmosphere::',
        'composition_style_0035',
    ),
    (
        '盛夏老街折扇遮阳',
        'walking on a historic old street on a hot summer day, 1.3::close-up on her face, framed by the fan::, shielding her face from the sun with a beautiful, open folding fan, looking out with curious eyes, wearing a modern, elegant qipao-style dress, 1.4::the intricate design of the traditional fan is in sharp focus::, 1.2::harsh, bright sunlight creates strong shadows on the red brick walls in the background, cultural, hot, slice of life atmosphere::',
        'composition_style_0036',
    ),
    (
        '秋日山路徒步回望',
        'on a mountain trail in autumn at golden hour, 1.2::cowboy shot, three-quarter view::, pausing her hike to look back with a bright, happy smile, wearing a lightweight windbreaker jacket, 1.5::surrounded by a vast, beautiful sea of silvergrass (pampas grass) that is glowing golden in the sunset and waving in the breeze::, 1.2::the background is a silhouette of distant mountains against a warm, colorful sky, energetic, breathtaking nature, Taiwanese autumn atmosphere::',
        'composition_style_0037',
    ),
    (
        '秋日校园咖啡馆沉思',
        'sitting by the window in a cozy campus cafe in autumn, 1.3::close-up on her face and upper body::, resting her chin on her hand with a calm, thoughtful expression, a cup of latte beside her, wearing a soft beige knit sweater, 1.4::soft afternoon sunlight streams through the window, creating a warm and gentle light on her face::, 1.2::through the window, the leaves of the trees have turned yellow and brown, creating a beautiful autumn view, peaceful, studious atmosphere::',
        'composition_style_0038',
    ),
    (
        '台北河滨骑行',
        'riding a bicycle in a riverside park in Taipei at dusk, 1.2::cowboy shot, from the side, panning shot::, looking towards the river with a content and relaxed smile, wearing an oversized hoodie, 1.4::the sky is a beautiful twilight gradient of deep blue and orange, and the city lights from the opposite bank are reflecting on the water surface::, 1.2::the iconic Taipei 101 is visible in the distant skyline, cool autumn breeze, peaceful, urban sports atmosphere::',
        'composition_style_0039',
    ),
    (
        '塞纳河旧书摊选书',
        'browsing a traditional bouquiniste bookstall along the Seine river in Paris on a winter day, 1.2::tight medium shot, eye-level::, intently reading an old book she picked up, a focused and curious expression, wearing a stylish wool overcoat and a beret, 1.4::light snow is gently falling, dusting her shoulders and the iconic green book box::, 1.2::the background is a blurry view of a stone bridge and Parisian architecture, creating a romantic, intellectual, and timeless atmosphere::',
        'composition_style_0040',
    ),
    (
        '中央公园暮色滑冰',
        'ice skating at the Wollman Rink in Central Park at dusk, 1.2::cowboy shot, dynamic angle::, captured in a graceful spinning motion with a joyful, radiant smile, her cheeks flushed, wearing a white turtleneck sweater, a plaid skirt, and a red scarf, 1.4::the iconic New York City skyline is lit up in the background, visible through the bare winter trees::, 1.2::the background is a beautiful bokeh of other skaters and festive lights, creating an energetic, magical, and iconic winter atmosphere::',
        'composition_style_0041',
    ),
    (
        '祇园祭宵山人群回眸',
        'during the Yoiyama evening of the Gion Matsuri festival in Kyoto, 1.2::close-up, eye-level::, looking back over her shoulder with a bright, excited smile in a dense crowd, wearing a traditional yukata, holding a small fan, 1.5::the scene is warmly illuminated by thousands of traditional paper lanterns hanging from festival floats and historic machiya townhouses::, 1.2::the background is a beautiful bokeh of other people in yukatas, creating a vibrant, energetic, and culturally rich atmosphere::',
        'composition_style_0042',
    ),
    (
        '平溪天灯节放灯后仰望',
        'at the Pingxi Sky Lantern Festival in Taiwan at night, 1.2::medium shot, from a low angle::, looking up with a bright, hopeful smile after releasing a sky lantern, wearing a casual jacket, 1.5::the sky is filled with hundreds of glowing orange sky lanterns rising like a river of stars, creating a breathtaking and magical atmosphere::, 1.2::the railway tracks are crowded with people, and the old street shops are lit up in the background, festive, spiritual, and heartwarming::',
        'composition_style_0043',
    ),
    (
        '中秋苏州园林提灯',
        'in a classical Suzhou garden on Mid-Autumn Festival night, 1.2::cowboy shot, from the side::, holding a glowing rabbit-shaped lantern and resting a hand on a stone bridge railing, a gentle and serene expression, wearing an elegant Hanfu, 1.5::a bright full moon and its perfect reflection are visible on the calm lake surface::, 1.2::the scene is beautifully lit by the silver moonlight and the warm glow from her lantern, creating a poetic, tranquil, and timeless Chinese atmosphere::',
        'composition_style_0044',
    ),
    (
        '沙发上亲密共享耳机',
        "2girls, sitting close together on a sofa, 1.3::close-up on their faces::, afternoon sunlight from a window, warm and soft atmosphere, tangled earphone cable, shallow depth of field, cozy living room background, intimate, heartwarming moment, character 1: gently putting one of her earbuds into the other girl's ear, a gentle, smiling expression with eyes closed, character 2: looking slightly surprised, blushing, wide-eyed, slightly parted lips,",
        'composition_style_0045',
    ),
    (
        '夜市饰品摊前的双人挑选',
        "2girls, at a lively night market stall, 1.2::medium shot, eye-level::, 1.5::vibrantly illuminated by the bright lights of the accessory stall::, colorful bokeh of the bustling night market crowd and other stalls, energetic, cute, playful interaction, character 1: playfully putting a cute hairclip on the other girl's head, smiling fondly, teasing expression, character 2: looking at her reflection in a small mirror, surprised and blushing expression, holding a small mirror,",
        'composition_style_0046',
    ),
    (
        '明亮厨房里的双人蛋糕课',
        '2girls, making a cake together in a bright kitchen, 1.3::tight medium shot, focusing on their hands and faces::, both wearing aprons, 1.4::bright natural light floods the kitchen, the table is filled with baking ingredients and tools::, sweet, domestic, collaborative atmosphere, heartwarming, character 1: stands behind the other girl, gently guiding her hands to use a piping bag, a gentle, patient smile, character 2: focused but blushing from the closeness, looking down at the cake, slightly clumsy,',
        'composition_style_0047',
    ),
    (
        '淡水码头日落背影',
        "2girls, at the seaside at sunset, Tamsui Fisherman's Wharf, 1.2::medium shot, from behind::, looking at the beautiful sunset over the ocean, romantic, peaceful atmosphere, silhouettes against the sky, character 1: arm around the other girl's shoulder, head tilted slightly towards her, content expression, character 2: leaning her head on the other girl's shoulder, relaxed and safe expression, holding hands with her,",
        'composition_style_0048',
    ),
    (
        '阳明山海芋田捧花',
        '1girl, standing in a calla lily field at Yangmingshan, Taiwan, 1.2::cowboy shot, eye-level::, holding a freshly picked bouquet of white calla lilies with a happy, satisfied smile, wearing waders or rain boots, 1.5::surrounded by a vast, beautiful sea of pure white calla lilies under a bright spring sun::, 1.2::the background is a blurry view of green mountains and a hint of mist, creating a fresh and serene atmosphere, slice of life::',
        'composition_style_0049',
    ),
    (
        '山间茶屋品春茶',
        '1girl, sitting at a wooden table at an outdoor tea house in the mountains, 1.3::close-up on her face and the teacup::, savoring the aroma of fresh spring tea with a serene, intoxicated expression, her eyes are closed, wearing a simple white shirt, 1.5::the background is a magnificent, blurry view of vast, terraced green tea fields under a clear sky::, 1.2::a traditional tea set is on the table, peaceful, refined, zen atmosphere::',
        'composition_style_0050',
    ),
    (
        '红砖老巷里仰望繁花',
        '1girl, standing in a quiet, historic red-brick alley in southern Taiwan, 1.2::medium shot, from a low angle::, looking up with a gentle, amazed expression at the flowers above, wearing a simple white dress, 1.5::a massive, spectacular cascade of vibrant pink bougainvillea tumbles over the top of an old wall, creating a stunning floral waterfall::, 1.3::dappled sunlight creates intricate patterns of light and shadow on the brick wall, beautiful, slice of life, cultural atmosphere::',
        'composition_style_0051',
    ),
    (
        '春日草坪上的耳机午后',
        '1girl, lying on a lush green lawn in a park on a spring day, 1.4::extreme close-up on her face, from a high angle::, listening to music with headphones, a blissful and completely relaxed smile on her face with eyes closed, her head is resting on her arms, 1.5::soft spring sunlight warms her face, a few cherry blossom petals have fallen on her hair::, 1.2::the background is a beautiful, soft bokeh of green grass and sunlight, peaceful, serene, ultimate relaxation::',
        'composition_style_0052',
    ),
    (
        '盛夏缘侧纳凉',
        'sitting on the polished wooden veranda (engawa) of a traditional Japanese house on a hot summer afternoon, 1.2::medium shot, from a slightly low angle::, gently fanning herself with a round fan (uchiwa) and looking up at a wind chime with a calm, comfortable expression, wearing a light cotton yukata, 1.4::a beautiful, translucent glass wind chime (furin) is tinkling in the foreground breeze::, 1.2::the background is a lush green Japanese garden with strong, dark tree shadows cast by the intense sunlight, creating a tranquil, nostalgic atmosphere::',
        'composition_style_0053',
    ),
    (
        '澎湖海岸公路骑车回眸',
        'riding a scooter along a beautiful coastal road in Penghu, Taiwan on a sunny summer day, 1.2::cowboy shot, dynamic angle::, turning back with a joyful, carefree laugh, wearing a simple t-shirt and denim shorts, 1.5::her long hair is blowing dramatically in the strong sea breeze::, 1.3::the background is a stunning view of a turquoise blue ocean and unique basalt column cliffs, creating an adventurous, energetic, and free atmosphere::',
        'composition_style_0054',
    ),
    (
        '西湖石桥油纸伞清晨',
        'standing on a traditional arched stone bridge at West Lake in Hangzhou in the early morning, 1.2::medium shot, eye-level::, holding a beautiful oil-paper umbrella and looking out at the view with a serene expression, wearing an elegant qipao-style dress, 1.5::surrounded by a vast, magnificent field of giant green lotus leaves and blooming pink lotus flowers::, 1.3::a thin layer of morning mist hangs over the water, creating a poetic, timeless, and classically Chinese atmosphere::',
        'composition_style_0055',
    ),
    (
        '日本乡间夏夜萤火',
        'on a summer night in the Japanese countryside, 1.3::close-up on her face and hand::, looking with pure wonder and a gentle smile at a single firefly glowing on her outstretched fingertip, wearing a yukata, 1.5::the entire scene is magically illuminated by thousands of other flying fireflies, creating beautiful, glowing light trails and a spectacular bokeh effect::, 1.2::the background is a dark forest by a small stream, creating an enchanting, peaceful, and deeply magical atmosphere::',
        'composition_style_0056',
    ),
    (
        '秋日岚山竹林沉思',
        'in the Arashiyama Bamboo Grove in Kyoto during autumn, 1.2::medium shot, eye-level::, leaning against a thick bamboo stalk with a serene, contemplative expression, wearing an elegant traditional kimono, 1.5::beautiful, volumetric sunbeams are filtering through the tall bamboo stalks::, 1.3::a few vibrant red maple leaves are scattered on the green mossy ground, creating a strong color contrast, peaceful, aesthetic, and classically Japanese atmosphere::',
        'composition_style_0057',
    ),
    (
        '北京银杏大道拍胶片',
        'on a ginkgo-lined avenue in Beijing in autumn, 1.2::cowboy shot, three-quarter view::, raising a vintage film camera to take a picture with a happy, focused expression, wearing a classic khaki trench coat, 1.5::a beautiful, dense shower of golden ginkgo leaves is falling all around her::, 1.3::the ground is completely covered in a thick, golden carpet of leaves, creating a vibrant and spectacular autumn scene, bright sunny day::',
        'composition_style_0058',
    ),
    (
        '山间木屋夜里捧热饮',
        'inside a cozy wooden cabin at a mountain resort in Taiwan at night, 1.3::medium shot, eye-level::, curled up in a soft armchair wrapped in a wool blanket, cupping a warm mug with a comfortable expression, wearing a chunky turtleneck sweater, 1.5::the crackling fireplace is the only main light source, casting a warm, flickering glow on the entire scene::, 1.2::through the large window beside her, the moonlit, colorful autumn forest is visible, creating a strong contrast between the cold outside and the warmth inside, extremely cozy atmosphere::',
        'composition_style_0059',
    ),
    (
        '奈良公园喂小鹿',
        'crouching down in Nara Park, Japan during autumn, 1.2::medium shot, from a low angle::, carefully offering a deer cracker (shika senbei) to a small, bowing deer, a gentle and happy smile on her face, wearing a dress and a cardigan, 1.4::the ground is covered in a beautiful carpet of red and yellow fallen leaves::, 1.2::other deer and the eaves of a traditional temple are visible in the blurry background, heartwarming, interactive moment with nature, slice of life::',
        'composition_style_0060',
    ),
    (
        '札幌雪祭仰望雪雕',
        'at the Sapporo Snow Festival in Japan at night, 1.2::medium shot, from a low angle::, looking up at a massive, detailed snow sculpture with an expression of pure awe and wonder, wearing a thick down jacket, a knit hat, and a scarf, 1.5::a spectacular, color-changing projection mapping light show is illuminating the snow sculpture, casting vibrant hues on her and the surroundings::, 1.3::her warm breath is clearly visible in the freezing air, light snow is falling, creating a magical and festive winter atmosphere::',
        'composition_style_0061',
    ),
    (
        '乌来冬夜露天温泉',
        'soaking in a private, stone-lined outdoor hot spring (rotenburo) in Wulai, Taiwan on a winter night, 1.3::close-up on her face and shoulders::, her eyes are closed with an utterly relaxed and comfortable expression, 1.5::a large amount of thick, white steam is rising from the water, creating a dreamy and hazy atmosphere that obscures her body::, 1.2::the background is a blurry Japanese-style garden with bamboo and a stone lantern covered in frost, serene, healing, peaceful moment::',
        'composition_style_0062',
    ),
    (
        '雪后胡同里的糖葫芦',
        'walking in a traditional Beijing hutong after a heavy snow, 1.3::close-up on her face and the tanghulu::, taking a bite of a bright red tanghulu with a happy and satisfied expression, wearing a thick padded jacket and a scarf, 1.5::the vibrant red, crystal-coated candied fruit creates a strong contrast with the white snow scene::, 1.2::the gray brick walls and tiled roofs of the hutong houses are covered in a thick blanket of snow, creating a nostalgic, slice-of-life atmosphere::',
        'composition_style_0063',
    ),
    (
        '白川乡雪夜观景台',
        'standing on the observation deck overlooking Shirakawa-go village in Japan on a winter evening, 1.2::medium shot, from behind and to the side::, gazing at the view with a captivated and moved expression, wearing a long, thick overcoat and a scarf, 1.5::below, the entire village of Gassho-zukuri farmhouses is covered in deep snow, with warm, golden light glowing from their windows, creating a fairytale-like scenery::, 1.2::the sky is a deep twilight blue and snow is gently falling, magical, picturesque, and peaceful atmosphere::',
        'composition_style_0064',
    ),
)


def composition_scene_count():
    """返回完整场景数量。"""
    return len(COMPOSITION_SCENES)


def composition_scene(index=None):
    """按索引或随机选取完整场景，返回结构化字典。"""
    if not COMPOSITION_SCENES:
        raise ValueError("随机场景池为空")
    position = random.randrange(len(COMPOSITION_SCENES)) if index is None else int(index) % len(COMPOSITION_SCENES)
    title, prompt, entry_id = COMPOSITION_SCENES[position]
    return {
        "index": position,
        "title": title,
        "prompt": prompt,
        "entry_id": entry_id,
        "source": COMPOSITION_SOURCE,
    }


def composition_scene_payload():
    """返回 WebUI 可直接使用的场景标题和提示词。"""
    return [
        {"index": index, "title": title, "prompt": prompt, "entry_id": entry_id}
        for index, (title, prompt, entry_id) in enumerate(COMPOSITION_SCENES)
    ]


def validate_composition_scenes():
    """校验条目唯一性和 NAI 权重上限，返回错误列表。"""
    errors = []
    seen_titles = set()
    seen_ids = set()
    for title, prompt, entry_id in COMPOSITION_SCENES:
        if not title or title in seen_titles:
            errors.append(f"场景标题重复或为空：{title}")
        if not entry_id or entry_id in seen_ids:
            errors.append(f"场景 ID 重复或为空：{entry_id}")
        seen_titles.add(title)
        seen_ids.add(entry_id)
        for value in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)::", prompt):
            if float(value) > 1.5:
                errors.append(f"{entry_id} 权重超过 1.5：{value}")
    return errors
